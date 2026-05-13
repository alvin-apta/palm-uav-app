from __future__ import annotations

import json
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.all_models import AssetType, HealthClass, ImageryAsset, OrthomosaicJob, User
from app.services.geojson import feature_collection

router = APIRouter(prefix="/map", tags=["map"])


@router.get("/trees.geojson")
def trees_geojson(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
    health: HealthClass | None = None,
    job_id: str | None = None,
) -> dict:
    clauses = ["1=1"]
    params: dict[str, str] = {}
    if block_id:
        clauses.append("block_id = :block_id")
        params["block_id"] = block_id
    if health:
        clauses.append("health_class = :health")
        params["health"] = health.value
    if job_id:
        clauses.append("EXISTS (SELECT 1 FROM tree_observations obs WHERE obs.tree_id = trees.id AND obs.job_id = :job_id)")
        params["job_id"] = job_id
    rows = db.execute(
        text(
            f"""
            SELECT id, block_id, health_class, confidence, canopy_area_m2,
                   equivalent_diameter_m, vari, chm_m, lai_estimate,
                   ST_AsGeoJSON(geom)::json AS geometry
            FROM trees
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at DESC
            LIMIT 20000
            """
        ),
        params,
    ).mappings()
    features = [
        {
            "type": "Feature",
            "geometry": row["geometry"],
            "properties": {
                "id": row["id"],
                "block_id": row["block_id"],
                "health_class": row["health_class"],
                "confidence": row["confidence"],
                "canopy_area_m2": row["canopy_area_m2"],
                "equivalent_diameter_m": row["equivalent_diameter_m"],
                "vari": row["vari"],
                "chm_m": row["chm_m"],
                "lai_estimate": row["lai_estimate"],
            },
        }
        for row in rows
    ]
    return feature_collection(features)


@router.get("/detections.geojson")
def detections_geojson(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
    health: HealthClass | None = None,
    job_id: str | None = None,
) -> dict:
    clauses = ["CAST(a.asset_type AS TEXT) = 'cog'"]
    params: dict[str, str] = {}
    if block_id:
        clauses.append("d.block_id = :block_id")
        params["block_id"] = block_id
    if health:
        clauses.append("d.health_class = :health")
        params["health"] = health.value
    if job_id:
        clauses.append("d.job_id = :job_id")
        params["job_id"] = job_id
    rows = db.execute(
        text(
            f"""
            SELECT d.id, d.job_id, d.asset_id, d.block_id, d.health_class, d.confidence,
                   d.canopy_area_m2, d.bbox_json, d.raw_json
            FROM detections_raw d
            JOIN imagery_assets a ON a.id = d.asset_id
            WHERE {' AND '.join(clauses)}
            ORDER BY d.created_at DESC
            LIMIT 50000
            """
        ),
        params,
    ).mappings()
    features = []
    for row in rows:
        raw_json = row["raw_json"] or {}
        geometry = raw_json.get("bbox_geojson")
        if not geometry:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": {
                    "id": row["id"],
                    "job_id": row["job_id"],
                    "asset_id": row["asset_id"],
                    "block_id": row["block_id"],
                    "health_class": row["health_class"],
                    "confidence": row["confidence"],
                    "canopy_area_m2": row["canopy_area_m2"],
                    "bbox": row["bbox_json"],
                    "source": raw_json.get("source"),
                    "tile": raw_json.get("tile"),
                },
            }
        )
    return feature_collection(features)


@router.get("/cogs/{asset_id}/tilejson")
def cog_tilejson(
    asset_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    asset = db.get(ImageryAsset, asset_id)
    if not asset or asset.asset_type != AssetType.cog or not asset.cog_url:
        raise HTTPException(status_code=404, detail="COG asset not found")
    cog_url = quote(asset.cog_url, safe="")
    internal_tilejson_url = f"{settings.titiler_base_url}/cog/WebMercatorQuad/tilejson.json?url={cog_url}"
    tilejson_url = f"{settings.public_titiler_base_url}/cog/WebMercatorQuad/tilejson.json?url={cog_url}"
    raster_source = {
        "type": "raster",
        "tiles": [
            f"{settings.public_titiler_base_url}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}.png?url={cog_url}"
        ],
        "tileSize": 256,
    }
    bounds = None
    center = None
    try:
        response = httpx.get(internal_tilejson_url, timeout=10.0)
        response.raise_for_status()
        tilejson = response.json()
        bounds = tilejson.get("bounds")
        center = tilejson.get("center")
        if bounds:
            raster_source["bounds"] = bounds
    except Exception:
        pass
    return {
        "asset_id": asset.id,
        "tilejson_url": tilejson_url,
        "bounds": bounds,
        "center": center,
        "source": raster_source,
    }


@router.get("/cogs")
def list_cogs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
) -> list[dict]:
    query = select(ImageryAsset).where(ImageryAsset.asset_type == AssetType.cog)
    if block_id:
        query = query.where(ImageryAsset.block_id == block_id)
    assets = list(db.scalars(query.order_by(ImageryAsset.created_at.desc())).all())
    job_by_output_id = {}
    if assets:
        job_by_output_id = {
            job.output_asset_id: job
            for job in db.scalars(
                select(OrthomosaicJob).where(OrthomosaicJob.output_asset_id.in_([asset.id for asset in assets]))
            ).all()
            if job.output_asset_id
        }
    rows = []
    for asset in assets:
        job = job_by_output_id.get(asset.id)
        summary = job.summary_json if job else {}
        rows.append(
            {
                "id": asset.id,
                "block_id": asset.block_id,
                "original_filename": asset.original_filename,
                "cog_url": asset.cog_url,
                "created_at": asset.created_at,
                "job_id": job.id if job else None,
                "batch_index": summary.get("batch_index") if summary else None,
                "batch_total": summary.get("batch_total") if summary else None,
                "photo_assets": summary.get("photo_assets") if summary else None,
            }
        )
    return rows
