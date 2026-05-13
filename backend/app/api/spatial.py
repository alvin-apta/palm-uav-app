from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import User
from app.services.geojson import feature_collection

router = APIRouter(prefix="/spatial", tags=["spatial"])


@router.get("/unhealthy-near-roads")
def unhealthy_near_roads(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str,
    distance_m: float = 50.0,
) -> dict:
    rows = db.execute(
        text(
            """
            SELECT DISTINCT t.id, t.block_id, t.health_class, t.confidence,
                   ST_AsGeoJSON(t.geom)::json AS geometry
            FROM trees t
            JOIN access_roads r ON r.block_id = t.block_id
            WHERE t.block_id = :block_id
              AND t.health_class IN ('yellow_stressed', 'dead')
              AND ST_DWithin(t.geom::geography, r.geom::geography, :distance_m)
            ORDER BY t.confidence DESC
            """
        ),
        {"block_id": block_id, "distance_m": distance_m},
    ).mappings()
    return feature_collection(
        [
            {
                "type": "Feature",
                "geometry": row["geometry"],
                "properties": {
                    "id": row["id"],
                    "block_id": row["block_id"],
                    "health_class": row["health_class"],
                    "confidence": row["confidence"],
                    "distance_filter_m": distance_m,
                },
            }
            for row in rows
        ]
    )

