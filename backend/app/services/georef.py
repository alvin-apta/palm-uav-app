from __future__ import annotations

from math import cos, radians
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from app.services.analytics import calculate_gsd

GPS_TAGS = {value: key for key, value in ExifTags.GPSTAGS.items()}
TAGS = {value: key for key, value in ExifTags.TAGS.items()}


def _ratio_to_float(value: Any) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        return float(value[0]) / max(float(value[1]), 1e-9)
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        return float(value.numerator) / max(float(value.denominator), 1e-9)
    return float(value)


def _dms_to_decimal(value: Any, ref: str) -> float | None:
    try:
        degrees = _ratio_to_float(value[0])
        minutes = _ratio_to_float(value[1])
        seconds = _ratio_to_float(value[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in {"S", "W"}:
            decimal *= -1
        return decimal
    except Exception:
        return None


def _gps_ifd(exif: Any) -> dict[str, Any]:
    gps_tag = TAGS.get("GPSInfo")
    if not exif or gps_tag is None:
        return {}
    try:
        gps_info = exif.get_ifd(gps_tag)
    except Exception:
        gps_info = exif.get(gps_tag)
    if not hasattr(gps_info, "items"):
        return {}
    return {ExifTags.GPSTAGS.get(key, key): value for key, value in gps_info.items()}


def read_photo_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {"path": str(path)}
    with Image.open(path) as image:
        metadata["width_px"] = image.width
        metadata["height_px"] = image.height
        exif = image.getexif()
        gps = _gps_ifd(exif)
        if gps:
            lat = _dms_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef", "N"))
            lon = _dms_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef", "E"))
            if lat is not None and lon is not None:
                metadata["gps_lat"] = lat
                metadata["gps_lon"] = lon
            if "GPSAltitude" in gps:
                metadata["altitude_m"] = _ratio_to_float(gps["GPSAltitude"])
            if "GPSImgDirection" in gps:
                metadata["heading_deg"] = _ratio_to_float(gps["GPSImgDirection"])
        focal = exif.get(TAGS.get("FocalLength")) if exif else None
        if focal:
            metadata["focal_length_mm"] = _ratio_to_float(focal)
        for metadata_key, tag_name in (
            ("datetime_original", "DateTimeOriginal"),
            ("datetime_digitized", "DateTimeDigitized"),
            ("datetime", "DateTime"),
        ):
            tag_id = TAGS.get(tag_name)
            value = exif.get(tag_id) if exif and tag_id is not None else None
            if value:
                metadata[metadata_key] = str(value)
    return metadata


def pixel_to_geo(
    center_lat: float | None,
    center_lon: float | None,
    pixel_x: float,
    pixel_y: float,
    image_width_px: int | None,
    image_height_px: int | None,
    altitude_m: float | None,
    sensor_width_mm: float | None,
    focal_length_mm: float | None,
) -> tuple[float | None, float | None]:
    if None in (center_lat, center_lon, image_width_px, image_height_px, altitude_m, sensor_width_mm, focal_length_mm):
        return center_lat, center_lon
    gsd_m_px = calculate_gsd(float(altitude_m), float(sensor_width_mm), float(focal_length_mm), int(image_width_px))
    if gsd_m_px is None:
        return center_lat, center_lon
    dx_m = (pixel_x - float(image_width_px) / 2.0) * gsd_m_px
    dy_m = (pixel_y - float(image_height_px) / 2.0) * gsd_m_px
    lat = float(center_lat) - dy_m / 111_320.0
    lon = float(center_lon) + dx_m / (111_320.0 * max(cos(radians(float(center_lat))), 1e-6))
    return lat, lon
