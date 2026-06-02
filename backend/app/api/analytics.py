from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.all_models import AssetType, Block, HealthClass, ImageryAsset, InferenceJob, JobStatus, OrthomosaicJob, Tree, User
from app.services.analytics import calculate_gsd, estimate_ffb_kg

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/block/{block_id}/summary")
def block_summary(
    block_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    block = db.get(Block, block_id)
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    rows = db.execute(
        select(Tree.health_class, func.count(Tree.id)).where(Tree.block_id == block_id).group_by(Tree.health_class)
    ).all()
    counts = {health.value if isinstance(health, HealthClass) else str(health): count for health, count in rows}
    total = sum(counts.values())
    avg_diameter = db.scalar(select(func.avg(Tree.equivalent_diameter_m)).where(Tree.block_id == block_id))
    avg_lai = db.scalar(select(func.avg(Tree.lai_estimate)).where(Tree.block_id == block_id))
    avg_vari = db.scalar(select(func.avg(Tree.vari)).where(Tree.block_id == block_id))
    avg_confidence = db.scalar(select(func.avg(Tree.confidence)).where(Tree.block_id == block_id))
    estimated_ffb_per_tree = estimate_ffb_kg(float(avg_diameter), float(avg_lai)) if avg_diameter and avg_lai else None
    block_area_ha = _block_area_ha(db, block_id)
    expected_palms = (float(block.target_palms_ha) * block_area_ha) if block.target_palms_ha and block_area_ha else None
    photos = list(
        db.scalars(
            select(ImageryAsset)
            .where(ImageryAsset.block_id == block_id, ImageryAsset.asset_type == AssetType.photo)
            .order_by(ImageryAsset.created_at.desc())
        ).all()
    )
    cogs = list(
        db.scalars(
            select(ImageryAsset)
            .where(ImageryAsset.block_id == block_id, ImageryAsset.asset_type == AssetType.cog)
            .order_by(ImageryAsset.created_at.desc())
        ).all()
    )
    stitch_jobs = list(
        db.scalars(
            select(OrthomosaicJob)
            .where(OrthomosaicJob.block_id == block_id)
            .order_by(OrthomosaicJob.created_at.desc())
            .limit(100)
        ).all()
    )
    inference_jobs = list(
        db.scalars(
            select(InferenceJob)
            .where(InferenceJob.block_id == block_id)
            .order_by(InferenceJob.created_at.desc())
            .limit(20)
        ).all()
    )

    gps_count = sum(1 for asset in photos if asset.gps_lat is not None and asset.gps_lon is not None)
    altitude_values = [asset.altitude_m for asset in photos if asset.altitude_m is not None]
    gsd_values = [
        calculate_gsd(asset.altitude_m, asset.sensor_width_mm, asset.focal_length_mm, asset.width_px)
        for asset in photos
        if asset.altitude_m and asset.sensor_width_mm and asset.focal_length_mm and asset.width_px
    ]
    gsd_values = [value for value in gsd_values if value is not None]
    dimension_counts: dict[str, int] = {}
    for asset in photos:
        if asset.width_px and asset.height_px:
            key = f"{asset.width_px}x{asset.height_px}"
            dimension_counts[key] = dimension_counts.get(key, 0) + 1

    latest_run_jobs = _latest_stitch_run(stitch_jobs)
    latest_inference = inference_jobs[0] if inference_jobs else None
    failed_stitch_count = sum(1 for job in stitch_jobs if job.status == JobStatus.failed)
    completed_stitch_count = sum(1 for job in stitch_jobs if job.status == JobStatus.complete)
    failed_inference_count = sum(1 for job in inference_jobs if job.status == JobStatus.failed)
    completed_inference_count = sum(1 for job in inference_jobs if job.status == JobStatus.complete)
    latest_run_elapsed = _run_elapsed_seconds(latest_run_jobs)
    planted_fullness_pct = min(100.0, (total / expected_palms) * 100) if expected_palms else None
    not_planted_pct = max(0.0, 100.0 - planted_fullness_pct) if planted_fullness_pct is not None else None
    not_planted_area_ha = (block_area_ha * (not_planted_pct / 100.0)) if block_area_ha and not_planted_pct is not None else None
    small_canopy_inspection_area_ha = (block_area_ha * (counts.get("small_canopy", 0) / total)) if block_area_ha and total else None
    inspection_area_ha = (
        (not_planted_area_ha or 0.0) + (small_canopy_inspection_area_ha or 0.0)
        if block_area_ha and (not_planted_area_ha is not None or small_canopy_inspection_area_ha is not None)
        else None
    )
    insights = _build_insights(
        photo_count=len(photos),
        gps_count=gps_count,
        tree_total=total,
        small_canopy_count=counts.get("small_canopy", 0),
        large_canopy_count=counts.get("large_canopy", 0),
        cogs_count=len(cogs),
        latest_run_jobs=latest_run_jobs,
        failed_stitch_count=failed_stitch_count,
        latest_inference=latest_inference,
        block_area_ha=block_area_ha,
        inspection_area_ha=inspection_area_ha,
        not_planted_pct=not_planted_pct,
    )

    return {
        "block_id": block.id,
        "block_name": block.name,
        "population_count": total,
        "canopy_counts": counts,
        "health_counts": counts,
        "small_canopy_count": counts.get("small_canopy", 0),
        "medium_canopy_count": counts.get("medium_canopy", 0),
        "large_canopy_count": counts.get("large_canopy", 0),
        "small_canopy_pct": round((counts.get("small_canopy", 0) / total) * 100, 1) if total else 0,
        "large_canopy_pct": round((counts.get("large_canopy", 0) / total) * 100, 1) if total else 0,
        "average_canopy_diameter_m": round(float(avg_diameter), 3) if avg_diameter else None,
        "average_lai": round(float(avg_lai), 3) if avg_lai else None,
        "average_vari": round(float(avg_vari), 3) if avg_vari else None,
        "average_confidence": round(float(avg_confidence), 3) if avg_confidence else None,
        "estimated_ffb_kg_per_tree": round(float(estimated_ffb_per_tree), 2) if estimated_ffb_per_tree else None,
        "estimated_total_ffb_kg": round(float(estimated_ffb_per_tree) * total, 2) if estimated_ffb_per_tree else None,
        "forecast_note": "FFB estimate is advisory until calibrated with harvest records.",
        "area": {
            "block_area_ha": round(block_area_ha, 3) if block_area_ha else None,
            "target_palms_ha": round(float(block.target_palms_ha), 2) if block.target_palms_ha else None,
            "expected_palms": round(expected_palms, 1) if expected_palms else None,
            "planted_fullness_pct": round(planted_fullness_pct, 1) if planted_fullness_pct is not None else None,
            "not_planted_pct": round(not_planted_pct, 1) if not_planted_pct is not None else None,
            "not_planted_area_ha": round(not_planted_area_ha, 3) if not_planted_area_ha is not None else None,
            "small_canopy_inspection_area_ha": round(small_canopy_inspection_area_ha, 3) if small_canopy_inspection_area_ha is not None else None,
            "inspection_area_ha": round(inspection_area_ha, 3) if inspection_area_ha is not None else None,
        },
        "imagery": {
            "photo_count": len(photos),
            "gps_count": gps_count,
            "gps_coverage_pct": round((gps_count / len(photos)) * 100, 1) if photos else 0,
            "mean_altitude_m": round(sum(altitude_values) / len(altitude_values), 2) if altitude_values else None,
            "mean_gsd_cm_px": round((sum(gsd_values) / len(gsd_values)) * 100, 2) if gsd_values else None,
            "dimension_sets": dimension_counts,
            "map_layers": len(cogs),
        },
        "stitching": {
            "total_jobs": len(stitch_jobs),
            "completed_jobs": completed_stitch_count,
            "failed_jobs": failed_stitch_count,
            "latest_run_total": len(latest_run_jobs),
            "latest_run_complete": sum(1 for job in latest_run_jobs if job.status == JobStatus.complete),
            "latest_run_failed": sum(1 for job in latest_run_jobs if job.status == JobStatus.failed),
            "latest_run_elapsed_seconds": latest_run_elapsed,
            "completed_layers": len(cogs),
        },
        "inference": {
            "total_jobs": len(inference_jobs),
            "completed_jobs": completed_inference_count,
            "failed_jobs": failed_inference_count,
            "latest_status": latest_inference.status.value if latest_inference else "not_started",
            "latest_error_code": latest_inference.error_code if latest_inference else None,
            "latest_unique_trees": (latest_inference.summary_json or {}).get("unique_trees") if latest_inference else None,
        },
        "insights": insights,
    }


def _latest_stitch_run(jobs: list[OrthomosaicJob]) -> list[OrthomosaicJob]:
    if not jobs:
        return []
    latest_created = jobs[0].created_at
    return [job for job in jobs if job.created_at == latest_created]


def _run_elapsed_seconds(jobs: list[OrthomosaicJob]) -> int | None:
    completed_or_started = [job for job in jobs if job.started_at or job.completed_at]
    if not completed_or_started:
        return None
    starts = [job.created_at for job in completed_or_started if job.created_at]
    ends = [job.completed_at or job.started_at for job in completed_or_started if job.completed_at or job.started_at]
    if not starts or not ends:
        return None
    return max(0, int((max(ends) - min(starts)).total_seconds()))


def _block_area_ha(db: Session, block_id: str) -> float | None:
    area = db.scalar(
        text(
            """
            SELECT ST_Area(boundary::geography) / 10000.0
            FROM blocks
            WHERE id = :block_id AND boundary IS NOT NULL
            """
        ),
        {"block_id": block_id},
    )
    return float(area) if area else None


def _build_insights(
    *,
    photo_count: int,
    gps_count: int,
    tree_total: int,
    small_canopy_count: int,
    large_canopy_count: int,
    cogs_count: int,
    latest_run_jobs: list[OrthomosaicJob],
    failed_stitch_count: int,
    latest_inference: InferenceJob | None,
    block_area_ha: float | None,
    inspection_area_ha: float | None,
    not_planted_pct: float | None,
) -> list[str]:
    insights: list[str] = []
    if photo_count and gps_count < photo_count:
        insights.append("Some photos are missing GPS; map placement and stitching can drift.")
    if latest_run_jobs:
        completed = sum(1 for job in latest_run_jobs if job.status == JobStatus.complete)
        failed = sum(1 for job in latest_run_jobs if job.status == JobStatus.failed)
        if failed:
            insights.append(f"Latest stitch run completed {completed} of {len(latest_run_jobs)} batches; failed batches need more overlap or larger batches.")
        elif len(latest_run_jobs) > 1:
            insights.append("Latest stitch run produced multiple map layers; view all overlays together before judging coverage.")
    elif photo_count:
        insights.append("Photos are uploaded but no stitch run has started yet.")
    if cogs_count > 1:
        insights.append("Multiple orthomosaic layers are available; use the all-overlays map mode for block review.")
    if latest_inference is None and photo_count:
        insights.append("AI palm inference has not run yet for this block.")
    elif latest_inference and latest_inference.status == JobStatus.failed:
        insights.append(f"Latest AI inference failed: {latest_inference.error_code or 'unknown error'}.")
    if tree_total:
        if inspection_area_ha:
            insights.append(f"{inspection_area_ha:.2f} ha should be inspected for missing palms or suppressed canopy.")
        if not_planted_pct:
            insights.append(f"{not_planted_pct:.1f}% of the expected planting capacity is not currently mapped as planted.")
        if small_canopy_count:
            insights.append(f"{small_canopy_count} palms have small canopies; inspect young, missing, or suppressed palms in the field.")
        if large_canopy_count:
            insights.append(f"{large_canopy_count} palms have large canopies; check spacing and crown overlap in dense areas.")
    elif block_area_ha:
        insights.append("Block boundary exists, but no palms are mapped yet; run inference to estimate planted fullness.")
    if failed_stitch_count and not cogs_count:
        insights.append("No usable map layer yet; retry a unified low-memory stitch before using partial batches.")
    return insights[:8]
