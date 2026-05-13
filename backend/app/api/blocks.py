from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from geoalchemy2 import WKTElement
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.all_models import Block, Estate, Tree, User, UserRole
from app.schemas.blocks import BlockCreate, BlockRead, TreeRead
from app.services.geojson import polygon_geojson_to_wkt

router = APIRouter(prefix="/blocks", tags=["blocks"])


@router.post("", response_model=BlockRead)
def create_block(
    payload: BlockCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.owner, UserRole.manager))],
) -> Block:
    estate = None
    if payload.estate_id:
        estate = db.get(Estate, payload.estate_id)
    elif payload.estate_name:
        estate = db.scalar(select(Estate).where(Estate.name == payload.estate_name))
        if estate is None:
            estate = Estate(name=payload.estate_name, owner_id=user.id)
            db.add(estate)
            db.flush()
    if estate is None:
        raise HTTPException(status_code=400, detail="Estate is required")
    boundary_wkt = polygon_geojson_to_wkt(payload.boundary_geojson)
    block = Block(
        estate_id=estate.id,
        name=payload.name,
        planting_year=payload.planting_year,
        palm_spacing_m=payload.palm_spacing_m,
        target_palms_ha=payload.target_palms_ha,
        boundary=WKTElement(boundary_wkt, srid=4326) if boundary_wkt else None,
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    return block


@router.get("", response_model=list[BlockRead])
def list_blocks(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[Block]:
    return list(db.scalars(select(Block).order_by(Block.created_at.desc())).all())


@router.get("/{block_id}/trees", response_model=list[TreeRead])
def list_block_trees(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[Tree]:
    return list(db.scalars(select(Tree).where(Tree.block_id == block_id).order_by(Tree.health_class, Tree.id)).all())


@router.get("/{block_id}/boundary.geojson")
def block_boundary_geojson(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    row = db.execute(
        text("SELECT id, name, ST_AsGeoJSON(boundary)::json AS geometry FROM blocks WHERE id = :block_id"),
        {"block_id": block_id},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Block not found")
    return {
        "type": "Feature",
        "geometry": row["geometry"],
        "properties": {"id": row["id"], "name": row["name"]},
    }

