from __future__ import annotations

import io
import math
import zipfile
from typing import Annotated
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.all_models import Block, Mission, User, UserRole
from app.schemas.missions import MissionCreate, MissionImportRead, MissionRead

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("", response_model=MissionRead)
def create_mission(
    payload: MissionCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.owner, UserRole.manager, UserRole.operator))],
) -> Mission:
    if db.get(Block, payload.block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    mission = Mission(**payload.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission


@router.post("/import-plan", response_model=MissionImportRead)
async def import_mission_plan(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.owner, UserRole.manager, UserRole.operator))],
    block_id: str = Form(...),
    file: UploadFile = File(...),
) -> dict:
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    content = await file.read()
    summary = parse_mission_plan(content, file.filename or "mission.kmz")
    mission = Mission(
        block_id=block_id,
        mission_type="imported_plan",
        drone_name=summary.get("drone") or "Imported UAV plan",
        route_notes=_mission_summary_text(summary),
    )
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return {"mission": mission, "summary": summary}


@router.get("", response_model=list[MissionRead])
def list_missions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
) -> list[Mission]:
    query = select(Mission)
    if block_id:
        query = query.where(Mission.block_id == block_id)
    return list(db.scalars(query.order_by(Mission.created_at.desc()).limit(100)).all())


def parse_mission_plan(content: bytes, filename: str) -> dict:
    kml_docs = _extract_kml_documents(content, filename)
    if not kml_docs:
        raise HTTPException(status_code=400, detail="No KML/WPML document found in the uploaded mission file")
    points: list[tuple[float, float, float | None]] = []
    line_points: list[tuple[float, float, float | None]] = []
    polygon_rings: list[list[tuple[float, float, float | None]]] = []
    speeds: list[float] = []
    heights: list[float] = []
    names: list[str] = []
    wpml_values: dict[str, set[str]] = {}
    for doc_name, xml_text in kml_docs:
        root = ET.fromstring(xml_text)
        names.extend(_tag_texts(root, "name")[:3])
        points.extend(_coordinates_for_tag(root, "Point"))
        line_points.extend(_coordinates_for_tag(root, "LineString"))
        polygon_rings.extend(_polygon_rings(root))
        speeds.extend(_numeric_tag_values(root, ("speed", "flightSpeed", "autoFlightSpeed", "waypointSpeed", "globalTransitionalSpeed")))
        heights.extend(_numeric_tag_values(root, ("height", "executeHeight", "ellipsoidHeight", "waypointHeight")))
        for key in ("templateType", "flyToWaylineMode", "finishAction", "droneEnumValue", "payloadEnumValue"):
            values = _tag_texts(root, key)
            if values:
                wpml_values.setdefault(key, set()).update(values)
    route_points = line_points or points
    route_distance_m = _path_distance_m(route_points)
    coverage_area_ha = sum(_ring_area_ha(ring) for ring in polygon_rings) or None
    bounds = _bounds(route_points or [point for ring in polygon_rings for point in ring])
    if coverage_area_ha is None and bounds:
        coverage_area_ha = _bounds_area_ha(bounds)
    waypoint_count = len(points) or len(route_points)
    return {
        "filename": filename,
        "name": names[0] if names else filename,
        "waypoint_count": waypoint_count,
        "route_distance_m": round(route_distance_m, 1) if route_distance_m else None,
        "coverage_area_ha": round(coverage_area_ha, 3) if coverage_area_ha else None,
        "coverage_basis": "polygon" if polygon_rings else "route bounds estimate" if bounds else None,
        "avg_speed_m_s": round(sum(speeds) / len(speeds), 2) if speeds else None,
        "max_speed_m_s": round(max(speeds), 2) if speeds else None,
        "avg_height_m": round(sum(heights) / len(heights), 2) if heights else None,
        "min_height_m": round(min(heights), 2) if heights else None,
        "max_height_m": round(max(heights), 2) if heights else None,
        "bounds": bounds,
        "drone": _first_value(wpml_values.get("droneEnumValue")),
        "payload": _first_value(wpml_values.get("payloadEnumValue")),
        "template_type": _first_value(wpml_values.get("templateType")),
        "finish_action": _first_value(wpml_values.get("finishAction")),
        "source_documents": [name for name, _ in kml_docs],
    }


def _extract_kml_documents(content: bytes, filename: str) -> list[tuple[str, str]]:
    lowered = filename.lower()
    if lowered.endswith(".kml") or lowered.endswith(".wpml"):
        return [(filename, content.decode("utf-8", errors="ignore"))]
    if not (lowered.endswith(".kmz") or lowered.endswith(".zip")):
        raise HTTPException(status_code=400, detail="Upload a .kmz, .kml, .wpml, or .kmz.zip file")
    docs: list[tuple[str, str]] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for name in archive.namelist():
            if name.lower().endswith((".kml", ".wpml")):
                docs.append((name, archive.read(name).decode("utf-8", errors="ignore")))
    return docs


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _tag_texts(root: ET.Element, name: str) -> list[str]:
    values = []
    for element in root.iter():
        if _local_name(element.tag) == name and element.text and element.text.strip():
            values.append(element.text.strip())
    return values


def _numeric_tag_values(root: ET.Element, names: tuple[str, ...]) -> list[float]:
    values = []
    lowered = {name.lower() for name in names}
    for element in root.iter():
        if _local_name(element.tag).lower() not in lowered or not element.text:
            continue
        try:
            values.append(float(element.text.strip()))
        except ValueError:
            continue
    return values


def _coordinates_for_tag(root: ET.Element, geometry_name: str) -> list[tuple[float, float, float | None]]:
    coords = []
    for geometry in root.iter():
        if _local_name(geometry.tag) != geometry_name:
            continue
        for child in geometry.iter():
            if _local_name(child.tag) == "coordinates" and child.text:
                coords.extend(_parse_coordinates(child.text))
    return coords


def _polygon_rings(root: ET.Element) -> list[list[tuple[float, float, float | None]]]:
    rings = []
    for polygon in root.iter():
        if _local_name(polygon.tag) != "Polygon":
            continue
        for child in polygon.iter():
            if _local_name(child.tag) == "coordinates" and child.text:
                ring = _parse_coordinates(child.text)
                if len(ring) >= 3:
                    rings.append(ring)
    return rings


def _parse_coordinates(text_value: str) -> list[tuple[float, float, float | None]]:
    coords = []
    for token in text_value.replace("\n", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
            alt = float(parts[2]) if len(parts) > 2 and parts[2] else None
        except ValueError:
            continue
        coords.append((lon, lat, alt))
    return coords


def _path_distance_m(points: list[tuple[float, float, float | None]]) -> float:
    return sum(_distance_m(first, second) for first, second in zip(points, points[1:]))


def _distance_m(first: tuple[float, float, float | None], second: tuple[float, float, float | None]) -> float:
    lon1, lat1, _ = first
    lon2, lat2, _ = second
    radius = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bounds(points: list[tuple[float, float, float | None]]) -> list[float] | None:
    if not points:
        return None
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return [round(min(lons), 7), round(min(lats), 7), round(max(lons), 7), round(max(lats), 7)]


def _bounds_area_ha(bounds: list[float]) -> float:
    west, south, east, north = bounds
    avg_lat_rad = math.radians((south + north) / 2)
    width_m = abs(east - west) * 111320 * max(0.01, math.cos(avg_lat_rad))
    height_m = abs(north - south) * 110574
    return (width_m * height_m) / 10000


def _ring_area_ha(ring: list[tuple[float, float, float | None]]) -> float:
    if len(ring) < 3:
        return 0.0
    origin_lat = sum(point[1] for point in ring) / len(ring)
    scale_x = 111320 * max(0.01, math.cos(math.radians(origin_lat)))
    scale_y = 110574
    projected = [(point[0] * scale_x, point[1] * scale_y) for point in ring]
    area = 0.0
    for (x1, y1), (x2, y2) in zip(projected, projected[1:] + projected[:1]):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2 / 10000


def _first_value(values: set[str] | None) -> str | None:
    return sorted(values)[0] if values else None


def _mission_summary_text(summary: dict) -> str:
    lines = [
        f"Imported route: {summary.get('name') or summary.get('filename')}",
        f"Waypoints: {summary.get('waypoint_count') or '-'}",
        f"Route distance: {summary.get('route_distance_m') or '-'} m",
        f"Coverage: {summary.get('coverage_area_ha') or '-'} ha ({summary.get('coverage_basis') or 'unknown'})",
        f"Speed: avg {summary.get('avg_speed_m_s') or '-'} m/s, max {summary.get('max_speed_m_s') or '-'} m/s",
        f"Height: avg {summary.get('avg_height_m') or '-'} m",
    ]
    return "\n".join(lines)
