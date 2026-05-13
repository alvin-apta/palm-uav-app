from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models.all_models import AssetType, Block, ImageryAsset, User
from app.schemas.imagery import ImageryAssetRead
from app.services.georef import read_photo_metadata

router = APIRouter(prefix="/imagery", tags=["imagery"])

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
COG_EXTENSIONS = {".tif", ".tiff"}


def safe_upload_path(block_id: str, filename: str) -> Path:
    suffix = Path(filename).suffix.lower()
    target_dir = settings.upload_dir / block_id
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{uuid.uuid4().hex}{suffix}"


def optional_float(value: str | float | None, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a number") from exc


@router.post("/upload/photos", response_model=list[ImageryAssetRead])
def upload_photos(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str = Form(...),
    sensor_width_mm: str | None = Form(None),
    focal_length_mm: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> list[ImageryAsset]:
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    sensor_width = optional_float(sensor_width_mm, "Sensor width")
    focal_length = optional_float(focal_length_mm, "Focal length")
    created: list[ImageryAsset] = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in PHOTO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported photo file: {upload.filename}")
        stored_path = safe_upload_path(block_id, upload.filename or "photo.jpg")
        with stored_path.open("wb") as handle:
            shutil.copyfileobj(upload.file, handle)
        metadata = read_photo_metadata(stored_path)
        asset = ImageryAsset(
            block_id=block_id,
            asset_type=AssetType.photo,
            original_filename=upload.filename or stored_path.name,
            stored_path=str(stored_path),
            width_px=metadata.get("width_px"),
            height_px=metadata.get("height_px"),
            gps_lat=metadata.get("gps_lat"),
            gps_lon=metadata.get("gps_lon"),
            altitude_m=metadata.get("altitude_m"),
            heading_deg=metadata.get("heading_deg"),
            sensor_width_mm=sensor_width,
            focal_length_mm=focal_length or metadata.get("focal_length_mm"),
            metadata_json=metadata,
        )
        db.add(asset)
        created.append(asset)
    db.commit()
    for asset in created:
        db.refresh(asset)
    return created


@router.post("/upload/cog", response_model=ImageryAssetRead)
def upload_or_register_cog(
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    block_id: str = Form(...),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> ImageryAsset:
    if db.get(Block, block_id) is None:
        raise HTTPException(status_code=404, detail="Block not found")
    if not url and file is None:
        raise HTTPException(status_code=400, detail="Provide a COG URL or upload a GeoTIFF file")
    stored_path = ""
    original_name = "orthomosaic.tif"
    cog_url = url
    if file is not None:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in COG_EXTENSIONS:
            raise HTTPException(status_code=400, detail="COG uploads must be .tif or .tiff")
        target = safe_upload_path(block_id, file.filename or "orthomosaic.tif")
        with target.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)
        stored_path = str(target)
        original_name = file.filename or target.name
        cog_url = f"file://{target.as_posix()}"
    asset = ImageryAsset(
        block_id=block_id,
        asset_type=AssetType.cog,
        original_filename=original_name,
        stored_path=stored_path or str(cog_url),
        cog_url=cog_url,
        metadata_json={"registered_as_cog": True},
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset
