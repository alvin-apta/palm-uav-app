from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.all_models import Block, Mission, User, UserRole
from app.schemas.missions import MissionCreate, MissionRead

router = APIRouter(prefix="/missions", tags=["missions"])


@router.post("", response_model=MissionRead)
def create_mission(
    payload: MissionCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_roles(UserRole.owner, UserRole.manager, UserRole.operator))],
) -> Mission:
    if db.get(Block, payload.block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    mission = Mission(**payload.model_dump())
    db.add(mission)
    db.commit()
    db.refresh(mission)
    return mission


@router.get("", response_model=list[MissionRead])
def list_missions(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
) -> list[Mission]:
    query = select(Mission)
    if block_id:
        query = query.where(Mission.block_id == block_id)
    return list(db.scalars(query.order_by(Mission.created_at.desc()).limit(100)).all())

