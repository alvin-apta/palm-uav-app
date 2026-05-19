from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Callable

import httpx
from geoalchemy2 import WKTElement
from PIL import Image, ImageOps
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.all_models import AssetType, DetectionRaw, HealthClass, ImageryAsset, InferenceJob, JobStatus
from app.services.analytics import calculate_gsd, calculate_vari, equivalent_diameter, estimate_lai
from app.services.dedup import deduplicate_job
from app.services.georef import pixel_to_geo

REQUIRED_CLASSES = {"healthy", "yellow_stressed", "small_young", "dead"}
Image.MAX_IMAGE_PIXELS = None
ROBOFLOW_CLASS_MAP = {
    "healthy": "healthy",
    "yellow": "yellow_stressed",
    "yellow_stressed": "yellow_stressed",
    "small": "small_young",
    "small_young": "small_young",
    "dead": "dead",
}
OVERLAP_SUPPRESSION_IOU = 0.5
OVERLAP_SUPPRESSION_CENTER_RATIO = 0.25


def _fail_job(job: InferenceJob, code: str, message: str) -> None:
    job.status = JobStatus.failed
    job.error_code = code
    job.error_message = message
    job.completed_at = datetime.now(timezone.utc)
    job.summary_json = {
        **(job.summary_json or {}),
        "progress": 100,
        "stage": code,
        "friendly_error": _friendly_inference_error(code, message),
        "recommended_action": _recommended_inference_action(code),
    }


def _friendly_inference_error(code: str, message: str) -> str:
    if code == "model_not_configured":
        return "Palm tree detection model is not configured."
    if code == "model_load_failed":
        return "Palm tree detection model could not be loaded."
    if code == "orthomosaic_not_georeferenced":
        return "The stitched map is missing usable georeferencing, so detections cannot be placed on the Web-GIS map."
    if code == "inference_failed":
        return "AI inference failed while processing imagery."
    return message


def _recommended_inference_action(code: str) -> str:
    if code == "model_not_configured":
        return "Place trained YOLO palm-health weights at /models/palm_health.pt, then run inference again."
    if code == "model_load_failed":
        return "Check that the model has classes: healthy, yellow_stressed, small_young, dead."
    if code == "orthomosaic_not_georeferenced":
        return "Recreate the stitch job from original GPS-tagged photos, add GCP/RTK control, or upload a georeferenced COG before running inference."
    return "Check the job error and retry after fixing the input or model configuration."


def _load_model(weights_path: str):
    if weights_path.startswith("roboflow://"):
        model_id = weights_path.replace("roboflow://", "", 1).strip()
        if not settings.roboflow_api_key:
            raise FileNotFoundError("ROBOFLOW_API_KEY is not configured for hosted palm inference.")
        if not model_id:
            raise ValueError("Roboflow model id is missing.")
        return {"provider": "roboflow", "model_id": model_id}
    path = Path(weights_path)
    if not path.exists():
        raise FileNotFoundError(f"Model weights not found: {weights_path}")
    from ultralytics import YOLO  # Imported lazily so API can run without GPU/model deps.

    model = YOLO(str(path))
    names = set(model.names.values() if isinstance(model.names, dict) else model.names)
    missing = REQUIRED_CLASSES - names
    if missing:
        raise ValueError(f"Model is missing required classes: {', '.join(sorted(missing))}")
    return model


def _class_to_health(class_name: str) -> HealthClass | None:
    normalized = class_name.strip().lower().replace(" ", "_").replace("-", "_")
    mapped = ROBOFLOW_CLASS_MAP.get(normalized)
    if not mapped:
        return None
    return HealthClass(mapped)


def _bbox_center_xy(box_xyxy: list[float]) -> tuple[float, float, float, float, float, float]:
    x1, y1, x2, y2 = [float(value) for value in box_xyxy]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    return x1 + width / 2.0, y1 + height / 2.0, x1, y1, width, height


def _patch_vari_from_image(image: Image.Image, x: float, y: float, width: float, height: float) -> float | None:
    try:
        crop = image.crop((int(x), int(y), int(x + width), int(y + height)))
        if crop.width == 0 or crop.height == 0:
            return None
        red, green, blue = [float(value) for value in list(crop.convert("RGB").resize((1, 1)).getdata())[0]]
        return calculate_vari(red, green, blue)
    except Exception:
        return None


def _patch_vari(image_path: Path, x: float, y: float, width: float, height: float) -> float | None:
    try:
        with Image.open(image_path).convert("RGB") as image:
            return _patch_vari_from_image(image, x, y, width, height)
    except Exception:
        return None


def _apply_geotransform(geo_transform: list[float], pixel_x: float, pixel_y: float) -> tuple[float, float]:
    return (
        geo_transform[0] + pixel_x * geo_transform[1] + pixel_y * geo_transform[2],
        geo_transform[3] + pixel_x * geo_transform[4] + pixel_y * geo_transform[5],
    )


def _raster_georef(asset: ImageryAsset, image_path: Path, fallback_width: int, fallback_height: int) -> dict[str, Any] | None:
    metadata = asset.metadata_json or {}
    info: dict[str, Any] = {
        "width": int(asset.width_px or metadata.get("width") or fallback_width),
        "height": int(asset.height_px or metadata.get("height") or fallback_height),
        "bounds": metadata.get("bounds"),
        "epsg": metadata.get("epsg"),
        "geo_transform": metadata.get("geo_transform"),
    }
    try:
        completed = subprocess.run(
            ["gdalinfo", "-json", str(image_path)],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if completed.returncode == 0 and completed.stdout:
            payload = json.loads(completed.stdout)
            size = payload.get("size") or []
            if len(size) >= 2:
                info["width"] = int(size[0])
                info["height"] = int(size[1])
            info["geo_transform"] = payload.get("geoTransform") or info.get("geo_transform")
            stac = payload.get("stac") or {}
            epsg = stac.get("proj:epsg") or ((payload.get("coordinateSystem") or {}).get("id") or {}).get("code")
            if epsg:
                epsg_text = str(epsg).split(":")[-1]
                info["epsg"] = int(epsg_text) if epsg_text.isdigit() else epsg
            coords = ((payload.get("wgs84Extent") or {}).get("coordinates") or [[]])[0]
            if coords:
                lon_values = [float(coord[0]) for coord in coords if len(coord) >= 2]
                lat_values = [float(coord[1]) for coord in coords if len(coord) >= 2]
                if lon_values and lat_values:
                    info["bounds"] = [min(lon_values), min(lat_values), max(lon_values), max(lat_values)]
    except Exception:
        pass

    if not info.get("bounds") and str(info.get("epsg")) == "4326" and info.get("geo_transform"):
        width = float(info["width"])
        height = float(info["height"])
        corners = [
            _apply_geotransform(info["geo_transform"], 0, 0),
            _apply_geotransform(info["geo_transform"], width, 0),
            _apply_geotransform(info["geo_transform"], width, height),
            _apply_geotransform(info["geo_transform"], 0, height),
        ]
        info["bounds"] = [
            min(lon for lon, _ in corners),
            min(lat for _, lat in corners),
            max(lon for lon, _ in corners),
            max(lat for _, lat in corners),
        ]

    bounds = info.get("bounds")
    if not bounds or len(bounds) != 4:
        return None
    info["bounds"] = [float(value) for value in bounds]
    return info


def _pixel_to_wgs84(georef: dict[str, Any], pixel_x: float, pixel_y: float) -> tuple[float | None, float | None]:
    if str(georef.get("epsg")) == "4326" and georef.get("geo_transform"):
        lon, lat = _apply_geotransform(georef["geo_transform"], pixel_x, pixel_y)
        return float(lat), float(lon)
    west, south, east, north = georef["bounds"]
    width = max(float(georef["width"]), 1.0)
    height = max(float(georef["height"]), 1.0)
    lon = west + (pixel_x / width) * (east - west)
    lat = north - (pixel_y / height) * (north - south)
    return lat, lon


def _bbox_geojson(georef: dict[str, Any], x: float, y: float, width: float, height: float) -> dict[str, Any] | None:
    corners = [
        _pixel_to_wgs84(georef, x, y),
        _pixel_to_wgs84(georef, x + width, y),
        _pixel_to_wgs84(georef, x + width, y + height),
        _pixel_to_wgs84(georef, x, y + height),
    ]
    if any(lat is None or lon is None for lat, lon in corners):
        return None
    coordinates = [[lon, lat] for lat, lon in corners]
    coordinates.append(coordinates[0])
    return {"type": "Polygon", "coordinates": [coordinates]}


def _georef_pixel_area_m2(georef: dict[str, Any]) -> float | None:
    try:
        west, south, east, north = georef["bounds"]
        mid_lat = (south + north) / 2.0
        width = max(float(georef["width"]), 1.0)
        height = max(float(georef["height"]), 1.0)
        metres_per_pixel_x = abs(east - west) * 111_320.0 * max(math.cos(math.radians(mid_lat)), 1e-6) / width
        metres_per_pixel_y = abs(north - south) * 111_320.0 / height
        return metres_per_pixel_x * metres_per_pixel_y
    except Exception:
        return None


def _bbox_iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    ax0 = float(first.get("x") or 0.0)
    ay0 = float(first.get("y") or 0.0)
    ax1 = ax0 + max(float(first.get("w") or 0.0), 0.0)
    ay1 = ay0 + max(float(first.get("h") or 0.0), 0.0)
    bx0 = float(second.get("x") or 0.0)
    by0 = float(second.get("y") or 0.0)
    bx1 = bx0 + max(float(second.get("w") or 0.0), 0.0)
    by1 = by0 + max(float(second.get("h") or 0.0), 0.0)

    overlap_w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    overlap_h = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = overlap_w * overlap_h
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _same_crown_candidate(first: DetectionRaw, second: DetectionRaw) -> bool:
    first_box = first.bbox_json or {}
    second_box = second.bbox_json or {}
    if _bbox_iou(first_box, second_box) >= OVERLAP_SUPPRESSION_IOU:
        return True

    first_w = max(float(first_box.get("w") or 0.0), 0.0)
    first_h = max(float(first_box.get("h") or 0.0), 0.0)
    second_w = max(float(second_box.get("w") or 0.0), 0.0)
    second_h = max(float(second_box.get("h") or 0.0), 0.0)
    crown_scale = min(first_w, first_h, second_w, second_h)
    if crown_scale <= 0 or first.pixel_x is None or first.pixel_y is None or second.pixel_x is None or second.pixel_y is None:
        return False

    center_distance = math.hypot(float(first.pixel_x) - float(second.pixel_x), float(first.pixel_y) - float(second.pixel_y))
    return center_distance <= crown_scale * OVERLAP_SUPPRESSION_CENTER_RATIO


def _suppress_overlapping_detections(detections: list[DetectionRaw]) -> list[DetectionRaw]:
    selected: list[DetectionRaw] = []
    for detection in sorted(detections, key=lambda item: float(item.confidence or 0.0), reverse=True):
        if any(_same_crown_candidate(detection, kept) for kept in selected):
            continue
        selected.append(detection)
    return selected


def _run_model_on_asset(
    model: Any,
    asset: ImageryAsset,
    job: InferenceJob,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[DetectionRaw]:
    if asset.asset_type == AssetType.cog:
        return _run_model_on_cog(model, asset, job, progress_callback)
    if isinstance(model, dict) and model.get("provider") == "roboflow":
        return _run_roboflow_on_asset(model["model_id"], asset, job)

    image_path = Path(asset.stored_path)
    results = model(
        str(image_path),
        verbose=False,
        conf=settings.yolo_confidence,
        iou=settings.yolo_iou,
        agnostic_nms=True,
    )
    detections: list[DetectionRaw] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        for box in boxes:
            cls_index = int(box.cls[0].item())
            confidence = float(box.conf[0].item())
            class_name = str(result.names[cls_index])
            health_class = _class_to_health(class_name)
            if health_class is None:
                continue
            x_center, y_center, x, y, width, height = _bbox_center_xy(box.xyxy[0].tolist())
            lat, lon = pixel_to_geo(
                asset.gps_lat,
                asset.gps_lon,
                x_center,
                y_center,
                asset.width_px,
                asset.height_px,
                asset.altitude_m,
                asset.sensor_width_mm,
                asset.focal_length_mm,
            )
            gsd = None
            if asset.altitude_m and asset.sensor_width_mm and asset.focal_length_mm and asset.width_px:
                gsd = calculate_gsd(asset.altitude_m, asset.sensor_width_mm, asset.focal_length_mm, asset.width_px)
            canopy_area = (width * height * gsd * gsd) if gsd else None
            diameter = equivalent_diameter(canopy_area)
            vari = _patch_vari(image_path, x, y, width, height)
            detection = DetectionRaw(
                job_id=job.id,
                asset_id=asset.id,
                block_id=job.block_id,
                health_class=health_class,
                confidence=confidence,
                bbox_json={"x": x, "y": y, "w": width, "h": height},
                pixel_x=x_center,
                pixel_y=y_center,
                lat=lat,
                lon=lon,
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326) if lat is not None and lon is not None else None,
                canopy_area_m2=canopy_area,
                vari=vari,
                lai_estimate=estimate_lai(diameter),
                raw_json={"class_name": class_name, "source": "ultralytics"},
            )
            detections.append(detection)
    return _suppress_overlapping_detections(detections)


def _run_model_on_cog(
    model: Any,
    asset: ImageryAsset,
    job: InferenceJob,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[DetectionRaw]:
    if isinstance(model, dict) and model.get("provider") == "roboflow":
        raise RuntimeError("Hosted Roboflow inference is not enabled for stitched orthomosaic tiles. Use local YOLO weights for map inference.")

    image_path = Path(asset.stored_path)
    if not image_path.exists():
        raise RuntimeError(f"Stitched map file was not found: {image_path}")

    detections: list[DetectionRaw] = []
    with Image.open(image_path) as image:
        width, height = image.size
        georef = _raster_georef(asset, image_path, width, height)
        if georef is None:
            raise RuntimeError(
                "orthomosaic_not_georeferenced: The selected stitched orthomosaic has no usable CRS or WGS84 bounds."
            )
        asset.width_px = int(georef["width"])
        asset.height_px = int(georef["height"])
        pixel_area_m2 = _georef_pixel_area_m2(georef)

        tile_size = 1280
        overlap = 160
        stride = tile_size - overlap
        x_steps = list(range(0, max(width, 1), stride))
        y_steps = list(range(0, max(height, 1), stride))
        total_tiles = max(1, len(x_steps) * len(y_steps))
        tile_index = 0

        for y0 in y_steps:
            for x0 in x_steps:
                tile_index += 1
                x1 = min(x0 + tile_size, width)
                y1 = min(y0 + tile_size, height)
                crop = image.crop((x0, y0, x1, y1)).convert("RGB")
                results = model(
                    crop,
                    verbose=False,
                    imgsz=640,
                    conf=settings.yolo_confidence,
                    iou=settings.yolo_iou,
                    agnostic_nms=True,
                )
                for result in results:
                    boxes = getattr(result, "boxes", None)
                    if boxes is None:
                        continue
                    for box in boxes:
                        cls_index = int(box.cls[0].item())
                        confidence = float(box.conf[0].item())
                        class_name = str(result.names[cls_index])
                        health_class = _class_to_health(class_name)
                        if health_class is None:
                            continue
                        local_x_center, local_y_center, local_x, local_y, box_width, box_height = _bbox_center_xy(
                            box.xyxy[0].tolist()
                        )
                        global_x = x0 + local_x
                        global_y = y0 + local_y
                        global_x_center = x0 + local_x_center
                        global_y_center = y0 + local_y_center
                        lat, lon = _pixel_to_wgs84(georef, global_x_center, global_y_center)
                        canopy_area = (box_width * box_height * pixel_area_m2) if pixel_area_m2 else None
                        diameter = equivalent_diameter(canopy_area)
                        vari = _patch_vari_from_image(crop, local_x, local_y, box_width, box_height)
                        bbox_geojson = _bbox_geojson(georef, global_x, global_y, box_width, box_height)
                        detections.append(
                            DetectionRaw(
                                job_id=job.id,
                                asset_id=asset.id,
                                block_id=job.block_id,
                                health_class=health_class,
                                confidence=confidence,
                                bbox_json={
                                    "x": global_x,
                                    "y": global_y,
                                    "w": box_width,
                                    "h": box_height,
                                    "image_width": width,
                                    "image_height": height,
                                },
                                pixel_x=global_x_center,
                                pixel_y=global_y_center,
                                lat=lat,
                                lon=lon,
                                geom=WKTElement(f"POINT({lon} {lat})", srid=4326)
                                if lat is not None and lon is not None
                                else None,
                                canopy_area_m2=canopy_area,
                                vari=vari,
                                lai_estimate=estimate_lai(diameter),
                                raw_json={
                                    "class_name": class_name,
                                    "source": "ultralytics_tiled_orthomosaic",
                                    "asset_type": asset.asset_type.value,
                                    "bbox_geojson": bbox_geojson,
                                    "tile": {
                                        "index": tile_index,
                                        "total": total_tiles,
                                        "x": x0,
                                        "y": y0,
                                        "w": x1 - x0,
                                        "h": y1 - y0,
                                    },
                                    "georef": {
                                        "bounds": georef.get("bounds"),
                                        "epsg": georef.get("epsg"),
                                    },
                                },
                            )
                        )
                if progress_callback and (tile_index == total_tiles or tile_index % 5 == 0):
                    progress_callback(tile_index, total_tiles)
    return _suppress_overlapping_detections(detections)


def _run_roboflow_on_asset(model_id: str, asset: ImageryAsset, job: InferenceJob) -> list[DetectionRaw]:
    image_path = Path(asset.stored_path)
    params = {
        "api_key": settings.roboflow_api_key,
        "confidence": settings.roboflow_confidence,
        "overlap": settings.roboflow_overlap,
    }
    upload_file, upload_name, upload_mime, resize_scale = _roboflow_upload_file(image_path, asset.original_filename)
    try:
        response = httpx.post(
            f"https://detect.roboflow.com/{model_id}",
            params=params,
            files={"file": (upload_name, upload_file, upload_mime)},
            timeout=httpx.Timeout(120.0, connect=30.0),
        )
    finally:
        upload_file.close()
    if response.status_code == 413:
        raise RuntimeError(
            f"Roboflow request is still too large after resizing to {settings.roboflow_max_image_side}px. "
            "Lower ROBOFLOW_MAX_IMAGE_SIDE and recreate api/worker containers."
        )
    if response.status_code in {401, 403}:
        raise RuntimeError("Roboflow rejected the API key or this key cannot access the configured model.")
    response.raise_for_status()
    payload = response.json()
    detections: list[DetectionRaw] = []
    for prediction in payload.get("predictions", []):
        health_class = _class_to_health(str(prediction.get("class", "")))
        if health_class is None:
            continue
        confidence = float(prediction.get("confidence") or 0.0)
        width = float(prediction.get("width") or 0.0) / resize_scale
        height = float(prediction.get("height") or 0.0) / resize_scale
        x_center = float(prediction.get("x") or 0.0) / resize_scale
        y_center = float(prediction.get("y") or 0.0) / resize_scale
        x = x_center - width / 2.0
        y = y_center - height / 2.0
        lat, lon = pixel_to_geo(
            asset.gps_lat,
            asset.gps_lon,
            x_center,
            y_center,
            asset.width_px,
            asset.height_px,
            asset.altitude_m,
            asset.sensor_width_mm,
            asset.focal_length_mm,
        )
        gsd = None
        if asset.altitude_m and asset.sensor_width_mm and asset.focal_length_mm and asset.width_px:
            gsd = calculate_gsd(asset.altitude_m, asset.sensor_width_mm, asset.focal_length_mm, asset.width_px)
        canopy_area = (width * height * gsd * gsd) if gsd else None
        diameter = equivalent_diameter(canopy_area)
        vari = _patch_vari(image_path, x, y, width, height)
        detections.append(
            DetectionRaw(
                job_id=job.id,
                asset_id=asset.id,
                block_id=job.block_id,
                health_class=health_class,
                confidence=confidence,
                bbox_json={"x": x, "y": y, "w": width, "h": height},
                pixel_x=x_center,
                pixel_y=y_center,
                lat=lat,
                lon=lon,
                geom=WKTElement(f"POINT({lon} {lat})", srid=4326) if lat is not None and lon is not None else None,
                canopy_area_m2=canopy_area,
                vari=vari,
                lai_estimate=estimate_lai(diameter),
                raw_json={
                    "class_name": prediction.get("class"),
                    "source": "roboflow",
                    "model_id": model_id,
                    "resize_scale": resize_scale,
                    "max_image_side": settings.roboflow_max_image_side,
                },
            )
        )
    return detections


def _roboflow_upload_file(image_path: Path, original_filename: str):
    max_side = max(320, int(settings.roboflow_max_image_side or 1600))
    with Image.open(image_path) as image:
        image = ImageOps.exif_transpose(image)
        width, height = image.size
        largest_side = max(width, height)
        if largest_side <= max_side:
            return image_path.open("rb"), original_filename, _mime_type(image_path), 1.0

        resize_scale = max_side / largest_side
        resized_size = (max(1, round(width * resize_scale)), max(1, round(height * resize_scale)))
        resized = image.convert("RGB").resize(resized_size, Image.Resampling.LANCZOS)
        buffer = BytesIO()
        resized.save(buffer, format="JPEG", quality=85, optimize=True)
        buffer.seek(0)
        return buffer, f"{Path(original_filename).stem}_roboflow.jpg", "image/jpeg", resize_scale


def _mime_type(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    if path.suffix.lower() in {".tif", ".tiff"}:
        return "image/tiff"
    return "application/octet-stream"


async def run_inference_job(ctx: dict[str, Any], job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(InferenceJob, job_id)
        if job is None:
            return
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        job.summary_json = {
            **(job.summary_json or {}),
            "progress": 0,
            "stage": "loading_model",
            "processed_assets": 0,
            "yolo_confidence": settings.yolo_confidence,
            "yolo_iou": settings.yolo_iou,
        }
        db.commit()
        try:
            model = _load_model(job.model_weights_path)
        except FileNotFoundError as exc:
            _fail_job(job, "model_not_configured", str(exc))
            db.commit()
            return
        except Exception as exc:
            _fail_job(job, "model_load_failed", str(exc))
            db.commit()
            return

        assets = list(db.scalars(select(ImageryAsset).where(ImageryAsset.id.in_(job.asset_ids_json))).all())
        if not assets:
            _fail_job(
                job,
                "orthomosaic_not_georeferenced",
                "No stitched orthomosaic assets were available for this inference job.",
            )
            db.commit()
            return
        total_detections = 0
        try:
            total_assets = max(1, len(assets))
            for index, asset in enumerate(assets, start=1):
                job.summary_json = {
                    **(job.summary_json or {}),
                    "progress": min(95, int(((index - 1) / total_assets) * 95)),
                    "stage": "processing_stitched_maps",
                    "processed_assets": index - 1,
                    "total_assets": len(assets),
                    "current_asset": asset.original_filename,
                }
                db.commit()

                def update_tile_progress(tile_index: int, total_tiles: int) -> None:
                    asset_base = ((index - 1) / total_assets) * 95
                    asset_span = 95 / total_assets
                    job.summary_json = {
                        **(job.summary_json or {}),
                        "progress": min(95, int(asset_base + asset_span * (tile_index / max(total_tiles, 1)))),
                        "stage": "processing_stitched_map_tiles",
                        "processed_assets": index - 1,
                        "total_assets": len(assets),
                        "current_asset": asset.original_filename,
                        "current_tile": tile_index,
                        "total_tiles": total_tiles,
                    }
                    db.commit()

                detections = _run_model_on_asset(model, asset, job, update_tile_progress)
                db.add_all(detections)
                total_detections += len(detections)
                job.summary_json = {
                    **(job.summary_json or {}),
                    "progress": min(95, int((index / total_assets) * 95)),
                    "processed_assets": index,
                    "raw_detections": total_detections,
                }
                db.commit()
            db.commit()
            unique_trees = deduplicate_job(db, job.id)
            job.status = JobStatus.complete
            job.completed_at = datetime.now(timezone.utc)
            job.summary_json = {
                **(job.summary_json or {}),
                "progress": 100,
                "stage": "complete",
                "raw_detections": total_detections,
                "unique_trees": unique_trees,
                "assets": len(assets),
                "cog_assets": len(assets),
                "yolo_confidence": settings.yolo_confidence,
                "yolo_iou": settings.yolo_iou,
                "health_classes": sorted(REQUIRED_CLASSES),
            }
            db.commit()
        except Exception as exc:
            db.rollback()
            message = str(exc)
            code = "orthomosaic_not_georeferenced" if "orthomosaic_not_georeferenced" in message else "inference_failed"
            _fail_job(job, code, message)
            db.commit()
