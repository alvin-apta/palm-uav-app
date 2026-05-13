from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.all_models import JobStatus
from app.schemas.common import OrmModel


class InferenceJobCreate(BaseModel):
    block_id: str
    asset_ids: list[str] | None = None
    model_weights_path: str | None = None


class InferenceJobRead(OrmModel):
    id: str
    block_id: str
    status: JobStatus
    model_weights_path: str
    error_code: str | None
    error_message: str | None
    asset_ids_json: list[str]
    summary_json: dict
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

