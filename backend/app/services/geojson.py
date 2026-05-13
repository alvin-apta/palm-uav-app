from __future__ import annotations

from typing import Any


def polygon_geojson_to_wkt(geojson: dict[str, Any] | None) -> str | None:
    if not geojson:
        return None
    geometry = geojson.get("geometry", geojson)
    if geometry.get("type") != "Polygon":
        raise ValueError("Only Polygon boundaries are supported in v1")
    rings = geometry.get("coordinates") or []
    if not rings:
        return None
    ring_text = []
    for ring in rings:
        coords = [f"{float(lon)} {float(lat)}" for lon, lat in ring]
        ring_text.append(f"({', '.join(coords)})")
    return f"POLYGON({', '.join(ring_text)})"


def point_feature(lon: float, lat: float, properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lon, lat]},
        "properties": properties,
    }


def feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}

