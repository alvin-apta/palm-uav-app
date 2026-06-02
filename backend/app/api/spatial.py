from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import Block, User
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


@router.get("/block-area-grid")
def block_area_grid(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str,
    cells: int = 5,
) -> dict:
    block = db.get(Block, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    if cells < 1 or cells > 25:
        raise HTTPException(status_code=400, detail="Grid cell count must be between 1 and 25")
    rows = db.execute(
        text(
            """
            WITH block_geom AS (
              SELECT boundary AS geom
              FROM blocks
              WHERE id = :block_id AND boundary IS NOT NULL
            ),
            bounds AS (
              SELECT ST_XMin(geom) AS west, ST_YMin(geom) AS south,
                     ST_XMax(geom) AS east, ST_YMax(geom) AS north
              FROM block_geom
            ),
            grid AS (
              SELECT series.index,
                     ST_CollectionExtract(
                       ST_Intersection(
                         block_geom.geom,
                         ST_MakeEnvelope(
                           bounds.west + ((bounds.east - bounds.west) * series.index / :cells),
                           bounds.south,
                           bounds.west + ((bounds.east - bounds.west) * (series.index + 1) / :cells),
                           bounds.north,
                           4326
                         )
                       ),
                       3
                     ) AS geom
              FROM block_geom, bounds, generate_series(0, :cells - 1) AS series(index)
            )
            SELECT index + 1 AS area_index,
                   ST_AsGeoJSON(ST_Multi(geom))::json AS geometry,
                   ST_Area(geom::geography) / 10000.0 AS area_ha,
                   COUNT(t.id) AS tree_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'small_canopy') AS small_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'medium_canopy') AS medium_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'large_canopy') AS large_canopy_count
            FROM grid
            LEFT JOIN trees t ON t.block_id = :block_id AND ST_Covers(grid.geom, t.geom)
            WHERE NOT ST_IsEmpty(grid.geom)
            GROUP BY index, geom
            ORDER BY index
            """
        ),
        {"block_id": block_id, "cells": cells},
    ).mappings()
    features = []
    for row in rows:
        features.append(_area_summary_feature(row["geometry"], f"Area {row['area_index']}", row))
    if not features:
        raise HTTPException(status_code=404, detail="Block boundary is required to generate grid areas")
    return feature_collection(features)


@router.post("/area-summary")
def area_summary(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    payload: Annotated[dict, Body(...)],
) -> dict:
    block_id = payload.get("block_id")
    geometry = payload.get("geometry")
    name = payload.get("name") or "Drawn area"
    if not block_id or not geometry:
        raise HTTPException(status_code=400, detail="block_id and polygon geometry are required")
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    row = db.execute(
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
            SELECT ST_AsGeoJSON(ST_Multi(geom))::json AS geometry,
                   ST_Area(geom::geography) / 10000.0 AS area_ha,
                   COUNT(t.id) AS tree_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'small_canopy') AS small_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'medium_canopy') AS medium_canopy_count,
                   COUNT(t.id) FILTER (WHERE t.health_class = 'large_canopy') AS large_canopy_count
            FROM area
            LEFT JOIN trees t ON t.block_id = :block_id AND ST_Covers(area.geom, t.geom)
            WHERE NOT ST_IsEmpty(area.geom)
            GROUP BY area.geom
            """
        ),
        {"block_id": block_id, "geometry": json.dumps(geometry)},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=400, detail="Unable to summarize polygon")
    return _area_summary_feature(row["geometry"], name, row)


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
            "name": name,
            "area_ha": round(float(row["area_ha"] or 0), 3),
            "tree_count": int(row["tree_count"] or 0),
            "small_canopy_count": counts["small_canopy"],
            "medium_canopy_count": counts["medium_canopy"],
            "large_canopy_count": counts["large_canopy"],
            "dominant_health_class": dominant,
        },
    }
