from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models.all_models import Block, Mission, PrescriptionMap, Tree, User, UserRole
from app.services.exports import block_geopdf_bytes, kmz_bytes, prescription_bundle_bytes

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("/kmz/mission")
def export_mission_kmz(
    mission_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    mission = db.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Mission not found")
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <name>PalmOps Mission {mission.id}</name>
        <description>{mission.mission_type} mission. Create DJI waypoint route manually in v1.</description>
      </Document>
    </kml>
    """
    return StreamingResponse(
        io.BytesIO(kmz_bytes(kml)),
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition": f'attachment; filename="mission-{mission.id}.kmz"'},
    )


@router.post("/prescription")
def export_prescription(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_roles(UserRole.owner, UserRole.manager))],
) -> StreamingResponse:
    trees = list(db.scalars(select(Tree).where(Tree.block_id == block_id).order_by(Tree.health_class, Tree.id)).all())
    if not trees:
        raise HTTPException(status_code=404, detail="No trees found for prescription export")
    bundle = prescription_bundle_bytes(trees)
    db.add(
        PrescriptionMap(
            block_id=block_id,
            created_by_id=user.id,
            summary_json={
                "tree_count": len(trees),
                "formats": ["geojson", "csv", "kml", "kmz"],
                "note": "Spot-treatment output; exact chemical dose must be configured by manager.",
            },
        )
    )
    db.commit()
    return StreamingResponse(
        io.BytesIO(bundle),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="prescription-{block_id}.zip"'},
    )


@router.post("/geopdf/block")
def export_block_geopdf(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    trees = list(db.scalars(select(Tree).where(Tree.block_id == block_id).order_by(Tree.health_class, Tree.id)).all())
    boundary = db.execute(
        text(
            """
            SELECT ST_AsGeoJSON(boundary)::json AS geometry
            FROM blocks
            WHERE id = :block_id AND boundary IS NOT NULL
            """
        ),
        {"block_id": block_id},
    ).scalar()
    if not trees and not boundary:
        raise HTTPException(status_code=404, detail="No mapped block boundary or palms found for GeoPDF export")
    pdf = block_geopdf_bytes(block, trees, boundary)
    safe_name = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in block.name).strip("-") or block.id
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="geopdf-{safe_name}.pdf"'},
    )
