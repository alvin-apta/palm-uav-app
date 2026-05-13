from __future__ import annotations

from app.services.geojson import feature_collection, point_feature, polygon_geojson_to_wkt


def test_polygon_geojson_to_wkt() -> None:
    geojson = {
        "type": "Polygon",
        "coordinates": [[[101.0, 0.0], [101.1, 0.0], [101.1, 0.1], [101.0, 0.0]]],
    }
    assert polygon_geojson_to_wkt(geojson) == "POLYGON((101.0 0.0, 101.1 0.0, 101.1 0.1, 101.0 0.0))"


def test_feature_collection() -> None:
    feature = point_feature(101.0, 0.5, {"health_class": "healthy"})
    collection = feature_collection([feature])
    assert collection["type"] == "FeatureCollection"
    assert collection["features"][0]["geometry"]["coordinates"] == [101.0, 0.5]

