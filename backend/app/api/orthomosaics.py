from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.all_models import AssetType, Block, ImageryAsset, JobStatus, OrthomosaicJob, User
from app.schemas.orthomosaics import OrthomosaicJobCreate, OrthomosaicJobRead
from app.services.orthomosaic import assess_orthomosaic_readiness
from app.worker.queue import enqueue_orthomosaic

router = APIRouter(prefix="/orthomosaics", tags=["orthomosaics"])

DJI_FILENAME_RE = re.compile(r"(?:dji_fly_)?(?P<date>\d{8})_(?P<time>\d{6})_(?P<seq>\d+)", re.IGNORECASE)


def _photo_assets(db: Session, block_id: str, asset_ids: list[str] | None = None) -> list[ImageryAsset]:
    query = select(ImageryAsset).where(
        ImageryAsset.block_id == block_id,
        ImageryAsset.asset_type == AssetType.photo,
    )
    if asset_ids:
        query = query.where(ImageryAsset.id.in_(asset_ids))
    assets = list(db.scalars(query.order_by(ImageryAsset.created_at.asc(), ImageryAsset.original_filename.asc())).all())
    return sorted(assets, key=_stitch_asset_sort_key)


@router.get("/quality")
def orthomosaic_quality(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    assets = _photo_assets(db, block_id)
    selected_assets, selection_note = _default_stitch_assets(assets)
    quality = assess_orthomosaic_readiness(selected_assets)
    if selection_note:
        quality["available_image_count"] = len(assets)
        quality["selected_image_count"] = len(selected_assets)
        quality["selection_note"] = selection_note
        quality.setdefault("warnings", []).insert(0, selection_note)
    return quality


@router.post("/jobs", response_model=OrthomosaicJobRead)
async def create_orthomosaic_job(
    payload: OrthomosaicJobCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> OrthomosaicJob:
    if db.get(Block, payload.block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    available_assets = _photo_assets(db, payload.block_id, payload.asset_ids)
    if not available_assets:
        raise HTTPException(status_code=400, detail="No photo assets found for stitching")
    assets, selection_note = (available_assets, "") if payload.asset_ids else _default_stitch_assets(available_assets)

    quality = assess_orthomosaic_readiness(assets)
    if selection_note:
        quality["available_image_count"] = len(available_assets)
        quality["selected_image_count"] = len(assets)
        quality["selection_note"] = selection_note
        quality.setdefault("warnings", []).insert(0, selection_note)
    batches = _asset_batches(
        assets,
        batch_size=_positive_int(payload.options.get("split_batch_size")),
        overlap=_positive_int(payload.options.get("split_overlap")) or 0,
    )
    batch_total = len(batches)
    jobs: list[OrthomosaicJob] = []
    for batch_index, batch_assets in enumerate(batches, start=1):
        batch_quality = assess_orthomosaic_readiness(batch_assets)
        if selection_note:
            batch_quality["available_image_count"] = len(available_assets)
            batch_quality["selected_image_count"] = len(assets)
            batch_quality["selection_note"] = selection_note
            batch_quality.setdefault("warnings", []).insert(0, selection_note)
        batch_options = dict(payload.options)
        if batch_total > 1:
            batch_options["batch_index"] = batch_index
            batch_options["batch_total"] = batch_total
        estimated_seconds = estimate_stitch_seconds(len(batch_assets), batch_options)
        job = OrthomosaicJob(
            block_id=payload.block_id,
            requested_by_id=user.id,
            status=JobStatus.queued,
            engine=payload.engine,
            asset_ids_json=[asset.id for asset in batch_assets],
            options_json=batch_options,
            quality_json=batch_quality,
            summary_json={
                "photo_assets": len(batch_assets),
                "readiness": batch_quality["readiness"],
                "estimated_seconds": estimated_seconds,
                "batch_index": batch_index,
                "batch_total": batch_total,
                "stage": "queued",
            },
        )
        db.add(job)
        jobs.append(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
    created_ids = [job.id for job in jobs]
    for job in jobs:
        job.summary_json = {**(job.summary_json or {}), "created_batch_job_ids": created_ids}
    db.commit()
    try:
        for job in jobs:
            await enqueue_orthomosaic(job.id)
    except Exception as exc:
        for job in jobs:
            job.status = JobStatus.failed
            job.error_code = "queue_unavailable"
            job.error_message = str(exc)
        db.commit()
    db.refresh(jobs[0])
    return jobs[0]


def _default_stitch_assets(assets: list[ImageryAsset]) -> tuple[list[ImageryAsset], str]:
    if len(assets) < 3:
        return assets, ""
    groups: dict[tuple[int | None, int | None], list[ImageryAsset]] = {}
    for asset in assets:
        groups.setdefault((asset.width_px, asset.height_px), []).append(asset)
    if len(groups) <= 1:
        return assets, ""

    def score(item: tuple[tuple[int | None, int | None], list[ImageryAsset]]) -> tuple[int, int, int]:
        (width, height), group_assets = item
        gps_count = sum(1 for asset in group_assets if asset.gps_lat is not None and asset.gps_lon is not None)
        pixel_area = (width or 0) * (height or 0)
        return gps_count, pixel_area, len(group_assets)

    (width, height), selected = max(groups.items(), key=score)
    if len(selected) < 3:
        return assets, ""
    note = (
        f"Auto-selected {len(selected)} of {len(assets)} photos at {width or 'unknown'}x{height or 'unknown'} "
        "to avoid stitching mixed-resolution image sets."
    )
    return sorted(selected, key=_stitch_asset_sort_key), note


def _stitch_asset_sort_key(asset: ImageryAsset) -> tuple:
    metadata = asset.metadata_json or {}
    capture_time = (
        metadata.get("datetime_original")
        or metadata.get("datetime_digitized")
        or metadata.get("datetime")
        or metadata.get("capture_time")
    )
    filename = (asset.original_filename or "").lower()
    if capture_time:
        return (0, str(capture_time), filename)
    match = DJI_FILENAME_RE.search(filename)
    if match:
        return (1, match.group("date"), match.group("time"), int(match.group("seq")), filename)
    created_at = asset.created_at.isoformat() if asset.created_at else ""
    return (2, created_at, filename)


def _asset_batches(assets: list[ImageryAsset], batch_size: int | None, overlap: int = 0) -> list[list[ImageryAsset]]:
    if not batch_size or batch_size < 3 or len(assets) <= batch_size:
        return [assets]
    overlap = max(0, min(overlap, batch_size - 1))
    step = batch_size - overlap
    batches: list[list[ImageryAsset]] = []
    start = 0
    while start < len(assets):
        batch = assets[start : start + batch_size]
        if len(batch) >= 3:
            batches.append(batch)
        if start + batch_size >= len(assets):
            break
        start += step
    return batches or [assets]


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def estimate_stitch_seconds(image_count: int, options: dict) -> int:
    resize_max_px = _positive_int(options.get("resize_max_px"))
    low_memory = bool(options.get("low_memory_preset"))
    base_per_image = 80
    if low_memory:
        base_per_image = 45
    if resize_max_px:
        if resize_max_px <= 1600:
            base_per_image *= 0.45
        elif resize_max_px <= 2048:
            base_per_image *= 0.6
        elif resize_max_px <= 3072:
            base_per_image *= 0.8
    if options.get("fast-orthophoto"):
        base_per_image *= 0.75
    return int(180 + image_count * base_per_image)


def _related_jobs(db: Session, job: OrthomosaicJob, batch: bool) -> list[OrthomosaicJob]:
    if not batch:
        return [job]
    batch_ids = (job.summary_json or {}).get("created_batch_job_ids") or []
    if not batch_ids:
        return [job]
    return list(db.scalars(select(OrthomosaicJob).where(OrthomosaicJob.id.in_(batch_ids))).all())


def _cancel_nodeodm_task(task_uuid: str | None) -> str | None:
    if not task_uuid:
        return None
    try:
        with httpx.Client(base_url=settings.nodeodm_url, timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            response = client.post(f"/task/{task_uuid}/cancel")
            response.raise_for_status()
    except Exception as exc:
        return str(exc)
    return None


@router.get("/jobs", response_model=list[OrthomosaicJobRead])
def list_orthomosaic_jobs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str | None = None,
) -> list[OrthomosaicJob]:
    query = select(OrthomosaicJob)
    if block_id:
        query = query.where(OrthomosaicJob.block_id == block_id)
    query = query.order_by(OrthomosaicJob.created_at.desc()).limit(50)
    return list(db.scalars(query).all())


@router.post("/jobs/{job_id}/cancel")
def cancel_orthomosaic_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    batch: bool = False,
) -> dict:
    job = db.get(OrthomosaicJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Orthomosaic job not found")
    target_jobs = _related_jobs(db, job, batch)
    cancelled = 0
    nodeodm_errors: list[str] = []
    for target in target_jobs:
        if target.status not in {JobStatus.queued, JobStatus.running}:
            continue
        summary = target.summary_json or {}
        nodeodm_error = _cancel_nodeodm_task(summary.get("nodeodm_task_uuid"))
        if nodeodm_error:
            nodeodm_errors.append(nodeodm_error)
        target.status = JobStatus.failed
        target.error_code = "cancelled"
        target.error_message = "Cancelled by user."
        target.completed_at = datetime.now(timezone.utc)
        target.summary_json = {
            **summary,
            "nodeodm_stage": "cancelled",
            "nodeodm_progress": 100,
            "friendly_error": "Stitch job was stopped by the user.",
            "recommended_action": "Create a new stitch job when you are ready to retry.",
            "cancelled_at": target.completed_at.isoformat(),
        }
        cancelled += 1
    db.commit()
    return {"cancelled": cancelled, "batch": batch, "nodeodm_errors": nodeodm_errors[:3]}


@router.delete("/jobs/{job_id}")
def delete_orthomosaic_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    batch: bool = False,
) -> dict:
    job = db.get(OrthomosaicJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Orthomosaic job not found")
    target_jobs = _related_jobs(db, job, batch)
    running = [target for target in target_jobs if target.status == JobStatus.running]
    if running:
        raise HTTPException(status_code=409, detail="Stop running stitch jobs before removing them.")
    deleted = len(target_jobs)
    for target in target_jobs:
        db.delete(target)
    db.commit()
    return {"deleted": deleted, "batch": batch}


@router.get("/jobs/{job_id}", response_model=OrthomosaicJobRead)
def get_orthomosaic_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> OrthomosaicJob:
    job = db.get(OrthomosaicJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Orthomosaic job not found")
    return job


@router.get("/jobs/{job_id}/preview")
def preview_orthomosaic_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    job = db.get(OrthomosaicJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Orthomosaic job not found")
    if job.status != JobStatus.complete or not job.output_asset_id:
        raise HTTPException(status_code=400, detail="Stitch job is not complete yet")

    asset = db.get(ImageryAsset, job.output_asset_id)
    if asset is None or asset.asset_type != AssetType.cog or not asset.cog_url:
        raise HTTPException(status_code=404, detail="Completed orthomosaic asset not found")

    encoded_cog_url = quote(asset.cog_url, safe="")
    info, info_error = _fetch_titiler_json(f"{settings.titiler_base_url}/cog/info?url={encoded_cog_url}")
    tilejson, tilejson_error = _fetch_titiler_json(
        f"{settings.titiler_base_url}/cog/WebMercatorQuad/tilejson.json?url={encoded_cog_url}"
    )
    source_assets = _assets_by_ids(db, job.asset_ids_json)
    diagnostics = _orthomosaic_diagnostics(
        job=job,
        source_assets=source_assets,
        raster_info=info,
        tilejson=tilejson,
        titiler_error=info_error or tilejson_error,
    )

    return {
        "job_id": job.id,
        "block_id": job.block_id,
        "asset_id": asset.id,
        "asset_name": asset.original_filename,
        "preview_url": f"{settings.public_titiler_base_url}/cog/preview/1400x900.png?url={encoded_cog_url}",
        "tilejson_url": f"{settings.public_titiler_base_url}/cog/WebMercatorQuad/tilejson.json?url={encoded_cog_url}",
        "bounds": tilejson.get("bounds") if tilejson else None,
        "center": tilejson.get("center") if tilejson else None,
        "input_quality": job.quality_json,
        "raster_info": _preview_raster_info(info),
        "diagnostics": diagnostics,
    }


def _fetch_titiler_json(url: str) -> tuple[dict, str | None]:
    try:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        return response.json(), None
    except Exception as exc:
        return {}, str(exc)


def _assets_by_ids(db: Session, asset_ids: list[str]) -> list[ImageryAsset]:
    if not asset_ids:
        return []
    return list(db.scalars(select(ImageryAsset).where(ImageryAsset.id.in_(asset_ids))).all())


def _preview_raster_info(info: dict) -> dict:
    keys = ["bounds", "crs", "driver", "dtype", "count", "width", "height", "overviews", "colorinterp"]
    return {key: info.get(key) for key in keys if key in info}


def _orthomosaic_diagnostics(
    job: OrthomosaicJob,
    source_assets: list[ImageryAsset],
    raster_info: dict,
    tilejson: dict,
    titiler_error: str | None,
) -> dict:
    quality = job.quality_json or {}
    issues: list[str] = []
    recommendations = list(quality.get("recommendations") or [])

    if titiler_error:
        issues.append(f"TiTiler could not fully read the output raster: {titiler_error}")
    if quality.get("readiness") not in {None, "ready"}:
        issues.append(f"Input readiness is {str(quality.get('readiness')).replace('_', ' ')}.")
    if (quality.get("gps_coverage_pct") or 0) < 80:
        issues.append("Less than 80% of source photos have GPS EXIF, so the orthomosaic can be placed or warped incorrectly.")
    if len(quality.get("dimension_sets") or []) > 1:
        issues.append("Mixed image dimensions were stitched together; use one original image set with the same resolution.")
    if (quality.get("image_count") or 0) < 20:
        issues.append("Small image batches can align visually but still produce stretched or torn orthomosaics.")
    if not tilejson.get("bounds"):
        issues.append("The output has no web-map bounds, so it should not be trusted as a map layer yet.")
    if not raster_info.get("crs"):
        issues.append("The output raster has no coordinate reference system.")

    filenames = [asset.original_filename.lower() for asset in source_assets]
    if any("whatsapp" in filename for filename in filenames):
        issues.append("WhatsApp/compressed filenames were detected; use the original DJI SD-card photos for stitching.")

    severity_score = 0
    if quality.get("readiness") == "needs_gps_or_gcp":
        severity_score += 3
    if (quality.get("gps_coverage_pct") or 0) < 80:
        severity_score += 2
    if len(quality.get("dimension_sets") or []) > 1:
        severity_score += 2
    if (quality.get("image_count") or 0) < 20:
        severity_score += 1
    if titiler_error or not tilejson.get("bounds"):
        severity_score += 2

    if severity_score >= 4:
        level = "high"
        verdict = "Preview before mapping. This orthomosaic has high distortion risk."
    elif severity_score >= 2:
        level = "medium"
        verdict = "Usable for visual preview, but verify alignment before using it as a map layer."
    else:
        level = "low"
        verdict = "The raster metadata is map-ready. Still verify visually before analysis."

    return {
        "risk_level": level,
        "verdict": verdict,
        "issues": issues,
        "recommendations": recommendations,
    }
