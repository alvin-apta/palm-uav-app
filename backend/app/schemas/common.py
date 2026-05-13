from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GeoJSONFeatureCollection(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]]


class Message(BaseModel):
    message: str


class IdResponse(BaseModel):
    id: str


class Timestamped(OrmModel):
    created_at: datetime


class BBox(BaseModel):
    x: float
    y: float
    width: float = Field(alias="w")
    height: float = Field(alias="h")

