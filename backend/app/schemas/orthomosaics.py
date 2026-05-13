from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.all_models import JobStatus
from app.schemas.common import OrmModel


class OrthomosaicJobCreate(BaseModel):
    block_id: str
    asset_ids: list[str] | None = None
    engine: str = "nodeodm"
    options: dict[str, Any] = Field(default_factory=dict)


class OrthomosaicJobRead(OrmModel):
    id: str
    block_id: str
    output_asset_id: str | None
    status: JobStatus
    engine: str
    asset_ids_json: list[str]
    options_json: dict
    quality_json: dict
    summary_json: dict
    output_path: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
