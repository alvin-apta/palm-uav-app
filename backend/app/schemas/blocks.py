from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.all_models import HealthClass
from app.schemas.common import OrmModel


class EstateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class EstateRead(OrmModel):
    id: str
    name: str
    created_at: datetime


class BlockCreate(BaseModel):
    estate_id: str | None = None
    estate_name: str | None = "Demo Estate"
    name: str = Field(min_length=1, max_length=255)
    planting_year: int | None = None
    palm_spacing_m: float | None = None
    target_palms_ha: float | None = None
    boundary_geojson: dict[str, Any] | None = None


class BlockRead(OrmModel):
    id: str
    estate_id: str
    name: str
    planting_year: int | None
    palm_spacing_m: float | None
    target_palms_ha: float | None
    created_at: datetime


class TreeRead(OrmModel):
    id: str
    block_id: str
    lat: float
    lon: float
    health_class: HealthClass
    confidence: float
    canopy_area_m2: float | None
    equivalent_diameter_m: float | None
    vari: float | None
    chm_m: float | None
    lai_estimate: float | None

