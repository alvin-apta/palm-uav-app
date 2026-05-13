from __future__ import annotations

from types import SimpleNamespace

from app.services.orthomosaic import assess_orthomosaic_readiness


def _asset(**overrides):
    values = {
        "gps_lat": -6.2,
        "gps_lon": 106.8,
        "altitude_m": 70.0,
        "width_px": 4000,
        "height_px": 3000,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_orthomosaic_quality_ready_for_original_gps_photos():
    report = assess_orthomosaic_readiness([_asset() for _ in range(6)])

    assert report["image_count"] == 6
    assert report["gps_coverage_pct"] == 100.0
    assert report["readiness"] == "ready"
    assert report["warnings"] == []


def test_orthomosaic_quality_warns_for_compressed_gpsless_images():
    report = assess_orthomosaic_readiness([_asset(gps_lat=None, gps_lon=None, altitude_m=None) for _ in range(4)])

    assert report["gps_count"] == 0
    assert report["readiness"] == "needs_gps_or_gcp"
    assert any("GPS EXIF" in warning for warning in report["warnings"])
