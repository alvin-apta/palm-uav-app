from __future__ import annotations

import math


def calculate_gsd(altitude_m: float, sensor_width_mm: float, focal_length_mm: float, image_width_px: int) -> float | None:
    if altitude_m <= 0 or sensor_width_mm <= 0 or focal_length_mm <= 0 or image_width_px <= 0:
        return None
    return (altitude_m * sensor_width_mm) / (focal_length_mm * image_width_px)


def calculate_vari(red: float, green: float, blue: float) -> float | None:
    denominator = green + red - blue
    if abs(denominator) < 1e-9:
        return None
    return (green - red) / denominator


def calculate_chm(dsm: float | None, dtm: float | None) -> float | None:
    if dsm is None or dtm is None:
        return None
    return dsm - dtm


def equivalent_diameter(area_m2: float | None) -> float | None:
    if area_m2 is None or area_m2 < 0:
        return None
    return math.sqrt((4.0 * area_m2) / math.pi)


def estimate_lai(canopy_diameter_m: float | None, coefficient: float = 0.42, intercept: float = 0.8) -> float | None:
    if canopy_diameter_m is None or canopy_diameter_m <= 0:
        return None
    return max(0.0, coefficient * canopy_diameter_m + intercept)


def estimate_ffb_kg(canopy_diameter_m: float | None, lai: float | None, coefficient: float = 18.0) -> float | None:
    if canopy_diameter_m is None or lai is None:
        return None
    if canopy_diameter_m <= 0 or lai <= 0:
        return None
    return canopy_diameter_m * lai * coefficient

