from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
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
    insights = _build_insights(
        photo_count=len(photos),
        gps_count=gps_count,
        tree_total=total,
        unhealthy_count=counts.get("yellow_stressed", 0) + counts.get("dead", 0),
        dead_count=counts.get("dead", 0),
        cogs_count=len(cogs),
        latest_run_jobs=latest_run_jobs,
        failed_stitch_count=failed_stitch_count,
        latest_inference=latest_inference,
    )

    return {
        "block_id": block.id,
        "block_name": block.name,
        "population_count": total,
        "health_counts": counts,
        "unhealthy_count": counts.get("yellow_stressed", 0) + counts.get("dead", 0),
        "unhealthy_pct": round(((counts.get("yellow_stressed", 0) + counts.get("dead", 0)) / total) * 100, 1) if total else 0,
        "dead_count": counts.get("dead", 0),
        "young_count": counts.get("small_young", 0),
        "average_canopy_diameter_m": round(float(avg_diameter), 3) if avg_diameter else None,
        "average_lai": round(float(avg_lai), 3) if avg_lai else None,
        "average_vari": round(float(avg_vari), 3) if avg_vari else None,
        "average_confidence": round(float(avg_confidence), 3) if avg_confidence else None,
        "estimated_ffb_kg_per_tree": round(float(estimated_ffb_per_tree), 2) if estimated_ffb_per_tree else None,
        "estimated_total_ffb_kg": round(float(estimated_ffb_per_tree) * total, 2) if estimated_ffb_per_tree else None,
        "forecast_note": "FFB estimate is advisory until calibrated with harvest records.",
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


def _build_insights(
    *,
    photo_count: int,
    gps_count: int,
    tree_total: int,
    unhealthy_count: int,
    dead_count: int,
    cogs_count: int,
    latest_run_jobs: list[OrthomosaicJob],
    failed_stitch_count: int,
    latest_inference: InferenceJob | None,
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
        if dead_count:
            insights.append(f"{dead_count} dead palms detected; prioritize field verification and replanting checks.")
        if unhealthy_count:
            insights.append(f"{unhealthy_count} palms need attention based on current health classification.")
    if failed_stitch_count and not cogs_count:
        insights.append("No usable map layer yet; retry a unified low-memory stitch before using partial batches.")
    return insights[:8]
