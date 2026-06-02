from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import OrmModel


class MissionCreate(BaseModel):
    block_id: str
    mission_type: str = "inventory"
    pilot: str | None = None
    drone_name: str | None = "DJI Mini 5 Pro"
    route_notes: str | None = None
    planned_at: datetime | None = None


class MissionRead(OrmModel):
    id: str
    block_id: str
    mission_type: str
    pilot: str | None
    drone_name: str | None
    route_notes: str | None
    planned_at: datetime | None
    created_at: datetime


class MissionImportRead(BaseModel):
    mission: MissionRead
    summary: dict
