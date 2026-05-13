from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.all_models import AssetType, ImageryAsset, InferenceJob, JobStatus, OrthomosaicJob, User
from app.schemas.jobs import InferenceJobCreate, InferenceJobRead
from app.worker.inference import REQUIRED_CLASSES
from app.worker.queue import enqueue_inference

router = APIRouter(prefix="/inference/jobs", tags=["inference"])


@router.get("/model/status")
def model_status(
    _: Annotated[User, Depends(get_current_user)],
) -> dict:
    path = Path(settings.model_weights_path)
    local_configured = path.exists()
    hosted_configured = bool(settings.roboflow_api_key and settings.roboflow_model_id)
    configured = local_configured or hosted_configured
    provider = "local" if local_configured else "roboflow" if hosted_configured else "missing"
    return {
        "configured": configured,
        "provider": provider,
        "local_configured": local_configured,
        "roboflow_configured": hosted_configured,
        "path": str(path),
        "roboflow_model_id": settings.roboflow_model_id,
        "yolo_confidence": settings.yolo_confidence,
        "yolo_iou": settings.yolo_iou,
        "required_classes": sorted(REQUIRED_CLASSES),
        "message": (
            "Local palm health model is configured."
            if local_configured
            else "Hosted Roboflow palm health model is configured."
            if hosted_configured
            else "Missing palm detection model. Add /models/palm_health.pt or set ROBOFLOW_API_KEY."
        ),
        "setup_command": "docker compose exec api python /scripts/setup_palm_health_model.py --epochs 50 --base-model yolov8s.pt",
    }


@router.post("", response_model=InferenceJobRead)
async def create_inference_job(
    payload: InferenceJobCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> InferenceJob:
    query = select(ImageryAsset).where(
        ImageryAsset.block_id == payload.block_id,
        ImageryAsset.asset_type == AssetType.cog,
    )
    if payload.asset_ids:
        query = query.where(ImageryAsset.id.in_(payload.asset_ids))
    else:
        completed_outputs = select(OrthomosaicJob.output_asset_id).where(
            OrthomosaicJob.block_id == payload.block_id,
            OrthomosaicJob.status == JobStatus.complete,
            OrthomosaicJob.output_asset_id.is_not(None),
        )
        query = query.where(ImageryAsset.id.in_(completed_outputs))
    assets = list(db.scalars(query.order_by(ImageryAsset.created_at.desc())).all())
    if not assets:
        raise HTTPException(
            status_code=400,
            detail=(
                "No completed stitched orthomosaic found for inference. "
                "Create a stitch job first, wait until it is complete, then run AI inference on the stitched map."
            ),
        )
    model_weights_path = payload.model_weights_path or str(settings.model_weights_path)
    if not payload.model_weights_path and not Path(model_weights_path).exists() and settings.roboflow_api_key:
        model_weights_path = f"roboflow://{settings.roboflow_model_id}"
    job = InferenceJob(
        block_id=payload.block_id,
        requested_by_id=user.id,
        status=JobStatus.queued,
        model_weights_path=model_weights_path,
        asset_ids_json=[asset.id for asset in assets],
        summary_json={"source_assets": "stitched_orthomosaic", "cog_assets": len(assets), "photo_assets": 0},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        await enqueue_inference(job.id)
    except Exception as exc:
        job.status = JobStatus.failed
        job.error_code = "queue_unavailable"
        job.error_message = str(exc)
        db.commit()
        db.refresh(job)
    return job


@router.get("/{job_id}", response_model=InferenceJobRead)
def get_inference_job(
    job_id: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> InferenceJob:
    job = db.get(InferenceJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Inference job not found")
    return job


@router.get("", response_model=list[InferenceJobRead])
def list_inference_jobs(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[InferenceJob]:
    return list(db.scalars(select(InferenceJob).order_by(InferenceJob.created_at.desc()).limit(50)).all())
