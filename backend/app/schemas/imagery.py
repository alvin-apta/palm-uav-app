from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.all_models import AssetType
from app.schemas.common import OrmModel


class ImageryAssetRead(OrmModel):
    id: str
    block_id: str
    asset_type: AssetType
    original_filename: str
    stored_path: str
    cog_url: str | None
    width_px: int | None
    height_px: int | None
    gps_lat: float | None
    gps_lon: float | None
    altitude_m: float | None
    heading_deg: float | None
    created_at: datetime


class CogRegisterRequest(BaseModel):
    block_id: str
    url: str
    original_filename: str = "orthomosaic.tif"

