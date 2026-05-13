from __future__ import annotations

from app.services.georef import _gps_ifd


class ExifWithOffsetGps:
    def get_ifd(self, tag):
        raise ValueError("gps ifd is not available")

    def get(self, tag):
        return 12345


def test_gps_ifd_ignores_integer_gps_offsets():
    assert _gps_ifd(ExifWithOffsetGps()) == {}
