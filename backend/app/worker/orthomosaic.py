from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.all_models import ImageryAsset, JobStatus, OrthomosaicJob
from app.services.orthomosaic import (
    OrthomosaicConfigError,
    OrthomosaicRunError,
    assess_orthomosaic_readiness,
    build_output_asset,
    find_orthomosaic_output,
    mark_job_failed,
    prepare_odm_project,
    run_nodeodm_job,
    run_odm_command,
)


class OrthomosaicCancelled(RuntimeError):
    pass


async def run_orthomosaic_job(ctx: dict[str, Any], job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(OrthomosaicJob, job_id)
        if job is None:
            return
        if job.status != JobStatus.queued:
            return
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        job.summary_json = {
            **(job.summary_json or {}),
            "stage": "starting",
            "elapsed_seconds": 0,
        }
        db.commit()

        assets = list(db.scalars(select(ImageryAsset).where(ImageryAsset.id.in_(job.asset_ids_json))).all())
        job.quality_json = assess_orthomosaic_readiness(assets)
        if len(assets) < 3:
            mark_job_failed(job, "insufficient_images", "At least 3 overlapping photos are required for stitching.")
            db.commit()
            return

        try:
            project_dir = prepare_odm_project(job, assets)
            nodeodm_summary: dict[str, Any] = {}
            log = ""
            if job.engine == "nodeodm":
                def save_progress(progress: dict) -> None:
                    db.refresh(job)
                    if job.error_code == "cancelled":
                        raise OrthomosaicCancelled("Cancelled by user.")
                    job.summary_json = {
                        **(job.summary_json or {}),
                        "photo_assets": len(assets),
                        "elapsed_seconds": _elapsed_seconds(job),
                        **progress,
                    }
                    db.commit()

                output_path, nodeodm_summary = run_nodeodm_job(
                    job,
                    assets,
                    project_dir,
                    on_progress=save_progress,
                )
            else:
                log = run_odm_command(job, project_dir)
                output_path = find_orthomosaic_output(project_dir)
            if output_path is None:
                mark_job_failed(job, "orthomosaic_missing", "ODM finished but no orthomosaic GeoTIFF was found.")
                db.commit()
                return

            output_asset = build_output_asset(job, output_path, log)
            db.add(output_asset)
            db.flush()
            job.output_asset_id = output_asset.id
            job.output_path = str(output_path)
            job.status = JobStatus.complete
            job.completed_at = datetime.now(timezone.utc)
            job.summary_json = {
                **(job.summary_json or {}),
                "photo_assets": len(assets),
                "output_asset_id": output_asset.id,
                "output_path": str(output_path),
                "elapsed_seconds": _elapsed_seconds(job),
                "nodeodm_progress": 100 if job.engine == "nodeodm" else None,
                "nodeodm_stage": "complete" if job.engine == "nodeodm" else None,
                **nodeodm_summary,
            }
            db.commit()
        except OrthomosaicCancelled:
            mark_job_failed(job, "cancelled", "Cancelled by user.")
            job.summary_json = {
                **(job.summary_json or {}),
                "nodeodm_stage": "cancelled",
                "nodeodm_progress": 100,
                "friendly_error": "Stitch job was stopped by the user.",
                "recommended_action": "Create a new stitch job when you are ready to retry.",
            }
            db.commit()
        except OrthomosaicConfigError as exc:
            mark_job_failed(job, "odm_not_configured", str(exc))
            _attach_failure_context(job, exc)
            db.commit()
        except OrthomosaicRunError as exc:
            mark_job_failed(job, "odm_failed", str(exc))
            _attach_failure_context(job, exc)
            db.commit()
        except Exception as exc:
            db.rollback()
            mark_job_failed(job, "stitch_failed", str(exc))
            _attach_failure_context(job, exc)
            db.commit()


def _elapsed_seconds(job: OrthomosaicJob) -> int:
    start = job.started_at or job.created_at
    end = job.completed_at or datetime.now(timezone.utc)
    if start is None:
        return 0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0, int((end - start).total_seconds()))


def _attach_failure_context(job: OrthomosaicJob, exc: Exception) -> None:
    message = str(exc)
    lower_message = message.lower()
    if "not enough memory" in lower_message or "out of memory" in lower_message or "cannot allocate memory" in lower_message:
        friendly = "NodeODM ran out of memory while stitching this block."
        action = "Retry with Low Memory mode, resize images to 2048 px or lower, split into partial batches of 20-30 photos, or increase Docker/WSL memory."
    elif "cannot process dataset" in lower_message or "no valid point-cloud" in lower_message:
        friendly = "ODM could not build a connected reconstruction from these photos."
        action = "Check overlap and flight geometry. Capture a grid with about 80% front overlap and 70% side overlap, then retry."
    elif "timed out" in lower_message:
        friendly = "The stitch job exceeded the configured processing timeout."
        action = "Retry with smaller batches or lower resolution."
    elif "could not resize" in lower_message:
        friendly = "One or more photos could not be resized before stitching."
        action = "Check that all uploaded files are valid images and re-upload the original DJI photos."
    else:
        friendly = "The stitch job failed during ODM processing."
        action = "Open the job details, review the error, and retry with Low Memory mode if the dataset is large."
    job.summary_json = {
        **(job.summary_json or {}),
        "elapsed_seconds": _elapsed_seconds(job),
        "friendly_error": friendly,
        "recommended_action": action,
        "raw_error": message[-4000:],
    }
