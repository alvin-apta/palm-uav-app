from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from typing import Iterable

from app.models.all_models import Block, Tree
from app.services.geojson import feature_collection, point_feature


def trees_to_geojson(trees: Iterable[Tree]) -> dict:
    return feature_collection(
        [
            point_feature(
                tree.lon,
                tree.lat,
                {
                    "id": tree.id,
                    "block_id": tree.block_id,
                    "health_class": tree.health_class.value,
                    "confidence": tree.confidence,
                    "equivalent_diameter_m": tree.equivalent_diameter_m,
                    "vari": tree.vari,
                    "lai_estimate": tree.lai_estimate,
                },
            )
            for tree in trees
        ]
    )


def trees_to_csv(trees: list[Tree]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "tree_id",
            "block_id",
            "lat",
            "lon",
            "health_class",
            "confidence",
            "equivalent_diameter_m",
            "vari",
            "lai_estimate",
        ],
    )
    writer.writeheader()
    for tree in trees:
        writer.writerow(
            {
                "tree_id": tree.id,
                "block_id": tree.block_id,
                "lat": tree.lat,
                "lon": tree.lon,
                "health_class": tree.health_class.value,
                "confidence": tree.confidence,
                "equivalent_diameter_m": tree.equivalent_diameter_m,
                "vari": tree.vari,
                "lai_estimate": tree.lai_estimate,
            }
        )
    return buffer.getvalue()


def trees_to_kml(trees: list[Tree], name: str = "Palm prescription") -> str:
    placemarks = []
    for tree in trees:
        placemarks.append(
            f"""
            <Placemark>
              <name>{tree.health_class.value}</name>
              <description>Tree {tree.id}; confidence {tree.confidence:.3f}</description>
              <Point><coordinates>{tree.lon},{tree.lat},0</coordinates></Point>
            </Placemark>
            """
        )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <name>{name}</name>
        {''.join(placemarks)}
      </Document>
    </kml>
    """


def kmz_bytes(kml_text: str, filename: str = "doc.kml") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(filename, kml_text)
    return buffer.getvalue()


def prescription_bundle_bytes(trees: list[Tree]) -> bytes:
    geojson_text = json.dumps(trees_to_geojson(trees), ensure_ascii=False, indent=2)
    csv_text = trees_to_csv(trees)
    kml_text = trees_to_kml(trees)
    kmz = kmz_bytes(kml_text)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("prescription.geojson", geojson_text)
        archive.writestr("prescription.csv", csv_text)
        archive.writestr("prescription.kml", kml_text)
        archive.writestr("prescription.kmz", kmz)
    return buffer.getvalue()


def block_geopdf_bytes(block: Block, trees: list[Tree], boundary: dict | None = None) -> bytes:
    bounds = _map_bounds(trees, boundary)
    if bounds is None:
        raise ValueError("GeoPDF export requires tree points or a block boundary")
    west, south, east, north = _pad_bounds(bounds)
    width = 842.0
    height = 595.0
    margin = 44.0
    title_height = 64.0
    legend_width = 150.0
    map_box = (margin, margin, width - margin - legend_width, height - margin - title_height)
    content = _geopdf_content(block, trees, boundary, (west, south, east, north), (width, height), map_box)
    return _write_geospatial_pdf(content, (width, height), map_box, (west, south, east, north), f"PalmOps {block.name} GeoPDF")


def _map_bounds(trees: list[Tree], boundary: dict | None) -> tuple[float, float, float, float] | None:
    points = [(tree.lon, tree.lat) for tree in trees]
    points.extend(_geojson_points(boundary))
    if not points:
        return None
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    return min(lons), min(lats), max(lons), max(lats)


def _pad_bounds(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    west, south, east, north = bounds
    lon_span = max(east - west, 0.0002)
    lat_span = max(north - south, 0.0002)
    return west - lon_span * 0.06, south - lat_span * 0.06, east + lon_span * 0.06, north + lat_span * 0.06


def _geojson_points(geometry: dict | None) -> list[tuple[float, float]]:
    if not geometry:
        return []
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates") or []
    points: list[tuple[float, float]] = []

    def append_pair(pair: list | tuple) -> None:
        if len(pair) >= 2:
            points.append((float(pair[0]), float(pair[1])))

    if geom_type == "Point":
        append_pair(coords)
    elif geom_type in {"LineString", "MultiPoint"}:
        for pair in coords:
            append_pair(pair)
    elif geom_type == "Polygon":
        for ring in coords:
            for pair in ring:
                append_pair(pair)
    elif geom_type == "MultiPolygon":
        for polygon in coords:
            for ring in polygon:
                for pair in ring:
                    append_pair(pair)
    return points


def _geopdf_content(
    block: Block,
    trees: list[Tree],
    boundary: dict | None,
    bounds: tuple[float, float, float, float],
    page_size: tuple[float, float],
    map_box: tuple[float, float, float, float],
) -> str:
    width, height = page_size
    mx, my, mw, mh = map_box
    commands = [
        "q",
        "1 1 1 rg",
        f"0 0 {width:.2f} {height:.2f} re f",
        "Q",
        _text(44, height - 38, f"PalmOps Offline Map: {block.name}", 18, bold=True),
        _text(44, height - 58, "GeoPDF export for Avenza Maps. Coordinate system: WGS 84 (EPSG:4326).", 9),
        _text(44, height - 74, f"Palms: {len(trees)}   Bounds: {bounds[0]:.6f}, {bounds[1]:.6f}, {bounds[2]:.6f}, {bounds[3]:.6f}", 8),
        "q",
        "0.95 0.98 0.96 rg",
        f"{mx:.2f} {my:.2f} {mw:.2f} {mh:.2f} re f",
        "0.12 0.20 0.18 RG 0.8 w",
        f"{mx:.2f} {my:.2f} {mw:.2f} {mh:.2f} re S",
        "Q",
    ]
    commands.extend(_grid_commands(bounds, map_box))
    commands.extend(_boundary_commands(boundary, bounds, map_box))
    commands.extend(_tree_commands(trees, bounds, map_box))
    commands.extend(_legend_commands(width - 44 - 126, height - 132, trees))
    commands.append(_north_arrow(width - 88, height - 238))
    commands.append(_scale_bar(bounds, map_box))
    return "\n".join(command for command in commands if command)


def _project(
    lon: float,
    lat: float,
    bounds: tuple[float, float, float, float],
    map_box: tuple[float, float, float, float],
) -> tuple[float, float]:
    west, south, east, north = bounds
    mx, my, mw, mh = map_box
    x = mx + ((lon - west) / (east - west)) * mw
    y = my + ((lat - south) / (north - south)) * mh
    return x, y


def _grid_commands(bounds: tuple[float, float, float, float], map_box: tuple[float, float, float, float]) -> list[str]:
    west, south, east, north = bounds
    commands = ["q", "0.82 0.88 0.84 RG 0.25 w"]
    for index in range(1, 4):
        lon = west + (east - west) * index / 4
        x, _ = _project(lon, south, bounds, map_box)
        commands.append(f"{x:.2f} {map_box[1]:.2f} m {x:.2f} {map_box[1] + map_box[3]:.2f} l S")
        lat = south + (north - south) * index / 4
        _, y = _project(west, lat, bounds, map_box)
        commands.append(f"{map_box[0]:.2f} {y:.2f} m {map_box[0] + map_box[2]:.2f} {y:.2f} l S")
    commands.append("Q")
    return commands


def _boundary_commands(boundary: dict | None, bounds: tuple[float, float, float, float], map_box: tuple[float, float, float, float]) -> list[str]:
    if not boundary:
        return []
    rings = []
    if boundary.get("type") == "Polygon":
        rings = boundary.get("coordinates") or []
    elif boundary.get("type") == "MultiPolygon":
        rings = [ring for polygon in boundary.get("coordinates") or [] for ring in polygon]
    commands = ["q", "0.12 0.38 0.20 RG 2.2 w", "0.60 0.85 0.64 rg"]
    for ring in rings:
        if len(ring) < 3:
            continue
        projected = [_project(float(pair[0]), float(pair[1]), bounds, map_box) for pair in ring]
        first_x, first_y = projected[0]
        path = [f"{first_x:.2f} {first_y:.2f} m"]
        path.extend(f"{x:.2f} {y:.2f} l" for x, y in projected[1:])
        path.append("h B")
        commands.append(" ".join(path))
    commands.append("Q")
    return commands


def _tree_commands(trees: list[Tree], bounds: tuple[float, float, float, float], map_box: tuple[float, float, float, float]) -> list[str]:
    colors = {
        "small_canopy": "0.86 0.15 0.15",
        "medium_canopy": "0.96 0.62 0.04",
        "large_canopy": "0.09 0.64 0.29",
    }
    commands = ["q", "0.20 0.25 0.22 RG 0.2 w"]
    max_points = 6000
    step = max(1, math.ceil(len(trees) / max_points))
    for tree in trees[::step]:
        x, y = _project(tree.lon, tree.lat, bounds, map_box)
        radius = 2.4
        commands.append(f"{colors.get(tree.health_class.value, '0.12 0.35 0.76')} rg")
        commands.append(_circle(x, y, radius))
    commands.append("Q")
    if step > 1:
        commands.append(_text(map_box[0], map_box[1] - 14, f"Palm display sampled every {step} records for PDF readability.", 7))
    return commands


def _legend_commands(x: float, y: float, trees: list[Tree]) -> list[str]:
    counts: dict[str, int] = {}
    for tree in trees:
        counts[tree.health_class.value] = counts.get(tree.health_class.value, 0) + 1
    rows = [
        ("small_canopy", "Small canopy", "0.86 0.15 0.15"),
        ("medium_canopy", "Medium canopy", "0.96 0.62 0.04"),
        ("large_canopy", "Large canopy", "0.09 0.64 0.29"),
    ]
    commands = [
        "q",
        "0.98 0.99 0.98 rg",
        f"{x:.2f} {y - 94:.2f} 126 118 re f",
        "0.72 0.78 0.73 RG 0.8 w",
        f"{x:.2f} {y - 94:.2f} 126 118 re S",
        "Q",
        _text(x + 12, y, "Legend", 11, bold=True),
    ]
    for index, (key, label, color) in enumerate(rows):
        row_y = y - 24 - (index * 24)
        commands.append(f"q {color} rg {_circle(x + 17, row_y + 4, 4)} Q")
        commands.append(_text(x + 30, row_y, f"{label}: {counts.get(key, 0)}", 8))
    return commands


def _north_arrow(x: float, y: float) -> str:
    return "\n".join(
        [
            "q",
            "0.10 0.18 0.14 rg",
            f"{x:.2f} {y + 44:.2f} m {x - 10:.2f} {y + 16:.2f} l {x + 10:.2f} {y + 16:.2f} l h f",
            "Q",
            _text(x - 4, y, "N", 12, bold=True),
        ]
    )


def _scale_bar(bounds: tuple[float, float, float, float], map_box: tuple[float, float, float, float]) -> str:
    west, south, east, north = bounds
    mx, my, mw, _ = map_box
    center_lat = (south + north) / 2
    meters_per_lon = 111_320 * max(0.01, math.cos(math.radians(center_lat)))
    map_width_m = (east - west) * meters_per_lon
    target = _nice_scale_length(map_width_m / 4)
    bar_width = (target / map_width_m) * mw if map_width_m else 0
    x = mx + 16
    y = my + 18
    return "\n".join(
        [
            "q",
            "0 0 0 RG 2 w",
            f"{x:.2f} {y:.2f} m {x + bar_width:.2f} {y:.2f} l S",
            f"{x:.2f} {y - 4:.2f} m {x:.2f} {y + 4:.2f} l S",
            f"{x + bar_width:.2f} {y - 4:.2f} m {x + bar_width:.2f} {y + 4:.2f} l S",
            "Q",
            _text(x, y + 8, f"{_format_distance(target)}", 8),
        ]
    )


def _nice_scale_length(value_m: float) -> float:
    if value_m <= 0:
        return 1.0
    exponent = math.floor(math.log10(value_m))
    base = value_m / (10**exponent)
    nice = 1 if base < 2 else 2 if base < 5 else 5
    return nice * (10**exponent)


def _format_distance(value_m: float) -> str:
    return f"{value_m / 1000:g} km" if value_m >= 1000 else f"{value_m:g} m"


def _circle(x: float, y: float, radius: float) -> str:
    c = radius * 0.5522847498
    return (
        f"{x + radius:.2f} {y:.2f} m "
        f"{x + radius:.2f} {y + c:.2f} {x + c:.2f} {y + radius:.2f} {x:.2f} {y + radius:.2f} c "
        f"{x - c:.2f} {y + radius:.2f} {x - radius:.2f} {y + c:.2f} {x - radius:.2f} {y:.2f} c "
        f"{x - radius:.2f} {y - c:.2f} {x - c:.2f} {y - radius:.2f} {x:.2f} {y - radius:.2f} c "
        f"{x + c:.2f} {y - radius:.2f} {x + radius:.2f} {y - c:.2f} {x + radius:.2f} {y:.2f} c f"
    )


def _text(x: float, y: float, text_value: str, size: int, *, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf {x:.2f} {y:.2f} Td ({_pdf_escape(text_value)}) Tj ET"


def _write_geospatial_pdf(
    content: str,
    page_size: tuple[float, float],
    map_box: tuple[float, float, float, float],
    bounds: tuple[float, float, float, float],
    title: str,
) -> bytes:
    width, height = page_size
    mx, my, mw, mh = map_box
    west, south, east, north = bounds
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
            "/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> "
            "/Contents 4 0 R "
            f"/VP [<< /Type /Viewport /Name ({_pdf_escape(title)}) /BBox [{mx:.2f} {my:.2f} {mx + mw:.2f} {my + mh:.2f}] "
            "<<MISSING>>"
            " >>] >>"
        ),
        f"<< /Length {len(content.encode('latin-1', errors='replace'))} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        "<< /Title ({}) /Creator (PalmOps Web-GIS) >>".format(_pdf_escape(title)),
    ]
    measure = (
        "/Measure << /Type /Measure /Subtype /GEO "
        "/Bounds [0 0 1 0 1 1 0 1] "
        f"/GPTS [{south:.10f} {west:.10f} {south:.10f} {east:.10f} {north:.10f} {east:.10f} {north:.10f} {west:.10f}] "
        "/LPTS [0 0 1 0 1 1 0 1] "
        "/GCS << /Type /GEOGCS /EPSG 4326 >> >>"
    )
    objects[2] = objects[2].replace("<<MISSING>>", measure)
    return _build_pdf(objects, info_object_number=7)


def _build_pdf(objects: list[str], *, info_object_number: int) -> bytes:
    buffer = io.BytesIO()
    buffer.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(buffer.tell())
        buffer.write(f"{index} 0 obj\n".encode("ascii"))
        buffer.write(body.encode("latin-1", errors="replace"))
        buffer.write(b"\nendobj\n")
    xref_offset = buffer.tell()
    buffer.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    buffer.write(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        buffer.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    buffer.write(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_object_number} 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return buffer.getvalue()


def _pdf_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
