from __future__ import annotations

from app.services.analytics import (
    calculate_chm,
    calculate_gsd,
    calculate_vari,
    equivalent_diameter,
    estimate_ffb_kg,
    estimate_lai,
)


def test_calculate_gsd() -> None:
    assert calculate_gsd(80, 13.2, 8.8, 4000) == 0.03
    assert calculate_gsd(0, 13.2, 8.8, 4000) is None


def test_calculate_vari() -> None:
    assert round(calculate_vari(red=80, green=120, blue=40), 4) == 0.25
    assert calculate_vari(red=50, green=50, blue=100) is None


def test_chm_and_equivalent_diameter() -> None:
    assert calculate_chm(34.5, 20.0) == 14.5
    assert round(equivalent_diameter(12.566370614359172), 3) == 4.0
    assert equivalent_diameter(-1) is None


def test_lai_and_ffb_estimates_are_advisory_math() -> None:
    lai = estimate_lai(5.0)
    assert round(lai, 4) == 2.9
    assert round(estimate_ffb_kg(5.0, lai), 4) == 261.0
