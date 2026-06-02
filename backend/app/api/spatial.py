from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import Block, BlockArea, User
from app.services.geojson import feature_collection

router = APIRouter(prefix="/spatial", tags=["spatial"])


@router.get("/small-canopy-near-roads")
def small_canopy_near_roads(
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
              AND t.health_class = 'small_canopy'
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


@router.get("/block-areas")
def list_block_areas(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str,
) -> dict:
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return feature_collection(_block_area_features(db, block_id=block_id))


@router.post("/block-areas")
def create_block_area(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    payload: Annotated[dict, Body(...)],
) -> dict:
    block_id = payload.get("block_id")
    geometry = payload.get("geometry")
    name = (payload.get("name") or "").strip()
    if not block_id or not geometry:
        raise HTTPException(status_code=400, detail="block_id and polygon geometry are required")
    if not name:
        raise HTTPException(status_code=400, detail="Area name is required")
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    area_id = str(uuid.uuid4())
    inserted = db.execute(
        text(
            """
            WITH input_area AS (
              SELECT ST_CollectionExtract(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326)), 3) AS geom
            ),
            block_geom AS (
              SELECT boundary AS geom
              FROM blocks
              WHERE id = :block_id AND boundary IS NOT NULL
            ),
            area AS (
              SELECT ST_CollectionExtract(
                       CASE
                         WHEN block_geom.geom IS NULL THEN input_area.geom
                         ELSE ST_Intersection(input_area.geom, block_geom.geom)
                       END,
                       3
                     ) AS geom
              FROM input_area
              LEFT JOIN block_geom ON true
            )
            INSERT INTO block_areas (id, block_id, created_by_id, name, geom)
            SELECT :area_id, :block_id, :created_by_id, :name, ST_Multi(geom)
            FROM area
            WHERE NOT ST_IsEmpty(area.geom)
            RETURNING id
            """
        ),
        {
            "area_id": area_id,
            "block_id": block_id,
            "created_by_id": user.id,
            "name": name[:255],
            "geometry": json.dumps(geometry),
        },
    ).scalar()
    if not inserted:
        raise HTTPException(status_code=400, detail="Area polygon does not overlap the selected block")
    db.commit()
    feature = _block_area_feature(db, area_id)
    if not feature:
        raise HTTPException(status_code=500, detail="Saved area could not be summarized")
    return feature


@router.delete("/block-areas/{area_id}")
def delete_block_area(
    area_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    area = db.get(BlockArea, area_id)
    if area is None:
        raise HTTPException(status_code=404, detail="Area not found")
    db.delete(area)
    db.commit()
    return {"deleted": True, "id": area_id}


def _block_area_feature(db: Session, area_id: str) -> dict | None:
    features = _block_area_features(db, area_id=area_id)
    return features[0] if features else None


def _block_area_features(db: Session, *, block_id: str | None = None, area_id: str | None = None) -> list[dict]:
    clauses = []
    params = {}
    if block_id:
        clauses.append("a.block_id = :block_id")
        params["block_id"] = block_id
    if area_id:
        clauses.append("a.id = :area_id")
        params["area_id"] = area_id
    rows = db.execute(
        text(
            f"""
            SELECT a.id, a.block_id, a.name, a.created_at,
                   ST_AsGeoJSON(a.geom)::json AS geometry,
                   ST_Area(a.geom::geography) / 10000.0 AS area_ha,
                   COUNT(t.id) AS tree_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'small_canopy') AS small_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'medium_canopy') AS medium_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'large_canopy') AS large_canopy_count
            FROM block_areas a
            LEFT JOIN trees t ON t.block_id = a.block_id AND ST_Covers(a.geom, t.geom)
            WHERE {' AND '.join(clauses) if clauses else '1=1'}
            GROUP BY a.id, a.block_id, a.name, a.created_at, a.geom
            ORDER BY a.created_at DESC, a.name ASC
            """
        ),
        params,
    ).mappings()
    return [_area_summary_feature(row["geometry"], row["name"], row) for row in rows]


def _area_summary_feature(geometry: dict, name: str, row: dict) -> dict:
    counts = {
        "small_canopy": int(row["small_canopy_count"] or 0),
        "medium_canopy": int(row["medium_canopy_count"] or 0),
        "large_canopy": int(row["large_canopy_count"] or 0),
    }
    dominant = max(counts, key=counts.get) if any(counts.values()) else None
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": {
            "id": row.get("id"),
            "block_id": row.get("block_id"),
            "name": name,
            "area_ha": round(float(row["area_ha"] or 0), 3),
            "tree_count": int(row["tree_count"] or 0),
            "small_canopy_count": counts["small_canopy"],
            "medium_canopy_count": counts["medium_canopy"],
            "large_canopy_count": counts["large_canopy"],
            "dominant_health_class": dominant,
            "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        },
    }
