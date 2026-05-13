from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Callable

import httpx
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.models.all_models import AssetType, ImageryAsset, JobStatus, OrthomosaicJob


class OrthomosaicConfigError(RuntimeError):
    pass


class OrthomosaicRunError(RuntimeError):
    pass


APP_ONLY_OPTIONS = {
    "output",
    "low_memory_preset",
    "resize_max_px",
    "split_batch_size",
    "split_overlap",
    "batch_index",
    "batch_total",
}

LOW_MEMORY_NODEODM_OPTIONS = {
    "cog": True,
    "gltf": False,
    "pc-ept": False,
    "3d-tiles": False,
    "dsm": False,
    "dtm": False,
    "skip-3dmodel": True,
    "skip-report": True,
    "fast-orthophoto": True,
    "feature-quality": "low",
    "pc-quality": "lowest",
    "orthophoto-resolution": 12,
    "max-concurrency": 2,
}


def assess_orthomosaic_readiness(assets: list[ImageryAsset]) -> dict:
    image_count = len(assets)
    gps_count = sum(1 for asset in assets if asset.gps_lat is not None and asset.gps_lon is not None)
    altitude_values = [asset.altitude_m for asset in assets if asset.altitude_m is not None]
    dimension_counts = Counter(
        (asset.width_px, asset.height_px)
        for asset in assets
        if asset.width_px is not None and asset.height_px is not None
    )
    gps_coverage = round((gps_count / image_count) * 100, 1) if image_count else 0.0
    warnings: list[str] = []

    if image_count < 3:
        warnings.append("Upload at least 3 overlapping nadir photos before running stitching.")
    elif image_count < settings.stitch_min_images:
        warnings.append(f"{settings.stitch_min_images}+ images is recommended for reliable orthomosaic stitching.")
    if gps_count < image_count:
        warnings.append("Some photos have no GPS EXIF. Use original DJI files or add GCPs for georeferencing.")
    if not altitude_values:
        warnings.append("Altitude metadata is missing, so GSD and scale checks will be weaker.")
    if len(dimension_counts) > 1:
        warnings.append("Mixed image dimensions detected. Use unedited originals from one camera mode.")

    if image_count < 3:
        readiness = "not_ready"
    elif gps_coverage < 80:
        readiness = "needs_gps_or_gcp"
    elif warnings:
        readiness = "usable_with_warnings"
    else:
        readiness = "ready"

    return {
        "image_count": image_count,
        "gps_count": gps_count,
        "gps_coverage_pct": gps_coverage,
        "altitude_mean_m": round(mean(altitude_values), 2) if altitude_values else None,
        "dimension_sets": [
            {"width_px": width, "height_px": height, "count": count}
            for (width, height), count in dimension_counts.most_common()
        ],
        "readiness": readiness,
        "warnings": warnings,
        "recommendations": [
            "Use original DJI SD-card images instead of WhatsApp/compressed copies.",
            "Fly nadir with roughly 80% front overlap and 70% side overlap.",
            "Use consistent altitude, exposure, white balance, and camera orientation.",
        ],
    }


def prepare_odm_project(job: OrthomosaicJob, assets: list[ImageryAsset]) -> Path:
    project_dir = settings.odm_project_dir / job.id
    image_dir = project_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for index, asset in enumerate(assets, start=1):
        source = Path(asset.stored_path)
        suffix = source.suffix.lower() or ".jpg"
        target = image_dir / f"{index:04d}_{_safe_filename(asset.original_filename, suffix)}"
        if target.exists():
            continue
        try:
            os.link(source, target)
        except OSError:
            shutil.copy2(source, target)
    return project_dir


def run_odm_command(job: OrthomosaicJob, project_dir: Path) -> str:
    command = _render_odm_command(job, project_dir)
    try:
        completed = subprocess.run(
            command,
            cwd=settings.odm_project_dir,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=settings.odm_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OrthomosaicRunError(f"ODM timed out after {settings.odm_timeout_seconds} seconds.") from exc
    log = completed.stdout or ""
    (project_dir / "palmops_odm.log").write_text(log[-80000:], encoding="utf-8")
    if completed.returncode != 0:
        raise OrthomosaicRunError(f"ODM exited with code {completed.returncode}. See palmops_odm.log.")
    return log


def run_nodeodm_job(
    job: OrthomosaicJob,
    assets: list[ImageryAsset],
    project_dir: Path,
    on_progress: Callable[[dict], None] | None = None,
) -> tuple[Path, dict]:
    if not settings.nodeodm_url.strip():
        raise OrthomosaicConfigError("NodeODM is not configured. Set NODEODM_URL before running stitch jobs.")

    upload_files, preprocessing_summary = _prepare_nodeodm_upload_files(job, assets, project_dir)
    if on_progress and preprocessing_summary:
        on_progress({"preprocessing": preprocessing_summary, "nodeodm_stage": "preprocessing", "nodeodm_progress": 0})
    task_uuid = _create_nodeodm_task(job, upload_files)
    if on_progress:
        on_progress(_nodeodm_progress_payload(task_uuid, {"uuid": task_uuid, "status": {"code": 10}, "progress": 0}))
    info = _wait_for_nodeodm_task(task_uuid, on_progress=on_progress)
    zip_path = _download_nodeodm_outputs(task_uuid, project_dir)
    output_path = _extract_nodeodm_orthophoto(zip_path, project_dir)
    return output_path, {"nodeodm_task_uuid": task_uuid, "nodeodm_info": info, "preprocessing": preprocessing_summary}


def find_orthomosaic_output(project_dir: Path) -> Path | None:
    candidates = [
        project_dir / "odm_orthophoto" / "odm_orthophoto.tif",
        project_dir / "odm_orthophoto" / "odm_orthphoto.tif",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def build_output_asset(job: OrthomosaicJob, output_path: Path, log_tail: str = "") -> ImageryAsset:
    return ImageryAsset(
        block_id=job.block_id,
        asset_type=AssetType.cog,
        original_filename=f"orthomosaic-{job.id}.tif",
        stored_path=str(output_path),
        cog_url=f"file://{output_path.as_posix()}",
        metadata_json={
            "source": "orthomosaic_job",
            "orthomosaic_job_id": job.id,
            "engine": job.engine,
            "is_cog_candidate": True,
            "log_tail": log_tail[-4000:],
        },
    )


def mark_job_failed(job: OrthomosaicJob, code: str, message: str) -> None:
    job.status = JobStatus.failed
    job.error_code = code
    job.error_message = message
    job.completed_at = datetime.now(timezone.utc)


def _render_odm_command(job: OrthomosaicJob, project_dir: Path) -> list[str]:
    template = settings.odm_command_template.strip()
    if not template:
        raise OrthomosaicConfigError(
            "ODM is not configured. Set ODM_COMMAND_TEMPLATE to an OpenDroneMap command before running stitch jobs."
        )
    rendered = template.format(
        project_root=settings.odm_project_dir.as_posix(),
        project_name=job.id,
        project_dir=project_dir.as_posix(),
    )
    return shlex.split(rendered)


def _prepare_nodeodm_upload_files(job: OrthomosaicJob, assets: list[ImageryAsset], project_dir: Path) -> tuple[list[dict], dict]:
    resize_max_px = _positive_int(job.options_json.get("resize_max_px"))
    if not resize_max_px:
        return (
            [{"path": Path(asset.stored_path), "filename": asset.original_filename} for asset in assets],
            {"enabled": False, "resize_max_px": None, "photo_assets": len(assets)},
        )

    resized_dir = project_dir / "resized_images"
    resized_dir.mkdir(parents=True, exist_ok=True)
    upload_files: list[dict] = []
    resized_count = 0
    skipped_count = 0
    original_pixels = 0
    resized_pixels = 0

    for index, asset in enumerate(assets, start=1):
        source = Path(asset.stored_path)
        target = resized_dir / f"{index:04d}_{_safe_filename(asset.original_filename, '.jpg')}"
        try:
            with Image.open(source) as image:
                exif = image.info.get("exif")
                original_width, original_height = image.size
                original_pixels += original_width * original_height
                image.thumbnail((resize_max_px, resize_max_px), Image.Resampling.LANCZOS)
                resized_width, resized_height = image.size
                resized_pixels += resized_width * resized_height
                if image.mode not in {"RGB", "L"}:
                    image = image.convert("RGB")
                save_kwargs = {"format": "JPEG", "quality": 90, "optimize": True}
                if exif:
                    save_kwargs["exif"] = exif
                image.save(target, **save_kwargs)
                resized_count += 1
        except (OSError, UnidentifiedImageError) as exc:
            skipped_count += 1
            raise OrthomosaicRunError(f"Could not resize {asset.original_filename}: {exc}") from exc
        upload_files.append({"path": target, "filename": target.name})

    reduction_pct = 0
    if original_pixels:
        reduction_pct = round((1 - (resized_pixels / original_pixels)) * 100, 1)
    return upload_files, {
        "enabled": True,
        "resize_max_px": resize_max_px,
        "photo_assets": len(assets),
        "resized_count": resized_count,
        "skipped_count": skipped_count,
        "pixel_reduction_pct": reduction_pct,
    }


def _create_nodeodm_task(job: OrthomosaicJob, upload_files: list[dict]) -> str:
    files = []
    handles = []
    try:
        for upload in upload_files:
            path = Path(upload["path"])
            handle = path.open("rb")
            handles.append(handle)
            files.append(("images", (_safe_filename(upload["filename"], path.suffix or ".jpg"), handle, _mime_type(path))))
        data = {
            "name": job.id,
            "outputs": json.dumps(["odm_orthophoto/odm_orthophoto.tif"]),
        }
        options = _nodeodm_options(job.options_json)
        if options:
            data["options"] = json.dumps(options)
        with httpx.Client(base_url=settings.nodeodm_url, timeout=httpx.Timeout(120.0, connect=30.0)) as client:
            response = client.post("/task/new", data=data, files=files)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise OrthomosaicRunError(f"NodeODM task creation failed: {exc}") from exc
    finally:
        for handle in handles:
            handle.close()
    task_uuid = payload.get("uuid")
    if not task_uuid:
        raise OrthomosaicRunError(f"NodeODM did not return a task uuid: {payload}")
    return str(task_uuid)


def _wait_for_nodeodm_task(task_uuid: str, on_progress: Callable[[dict], None] | None = None) -> dict:
    deadline = time.monotonic() + settings.odm_timeout_seconds
    latest: dict = {}
    with httpx.Client(base_url=settings.nodeodm_url, timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(f"/task/{task_uuid}/info")
                response.raise_for_status()
                latest = response.json()
            except httpx.HTTPError as exc:
                raise OrthomosaicRunError(f"NodeODM status polling failed: {exc}") from exc
            status = latest.get("status", {})
            code = status.get("code")
            if on_progress:
                on_progress(_nodeodm_progress_payload(task_uuid, latest))
            if code == 40:
                return latest
            if code in {30, 50}:
                message = latest.get("lastError") or status.get("label") or latest
                raise OrthomosaicRunError(f"NodeODM task failed: {message}")
            time.sleep(settings.nodeodm_poll_interval_seconds)
    raise OrthomosaicRunError(f"NodeODM timed out after {settings.odm_timeout_seconds} seconds. Last status: {latest}")


def _nodeodm_progress_payload(task_uuid: str, info: dict) -> dict:
    status = info.get("status") or {}
    code = status.get("code")
    stage = {
        10: "queued",
        20: "running",
        30: "failed",
        40: "complete",
        50: "canceled",
    }.get(code, status.get("label") or "running")
    progress = info.get("progress")
    if progress is None:
        progress = {10: 0, 20: 50, 30: 100, 40: 100, 50: 100}.get(code, 0)
    return {
        "nodeodm_task_uuid": task_uuid,
        "nodeodm_status_code": code,
        "nodeodm_stage": stage,
        "nodeodm_progress": max(0, min(100, int(progress))),
        "nodeodm_info": info,
    }


def _download_nodeodm_outputs(task_uuid: str, project_dir: Path) -> Path:
    zip_path = project_dir / "nodeodm_all.zip"
    with httpx.Client(base_url=settings.nodeodm_url, timeout=httpx.Timeout(settings.odm_timeout_seconds, connect=30.0)) as client:
        try:
            with client.stream("GET", f"/task/{task_uuid}/download/all.zip") as response:
                response.raise_for_status()
                with zip_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise OrthomosaicRunError(f"NodeODM output download failed: {exc}") from exc
    return zip_path


def _extract_nodeodm_orthophoto(zip_path: Path, project_dir: Path) -> Path:
    output_path = project_dir / "odm_orthophoto" / "odm_orthophoto.tif"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = archive.namelist()
            preferred = "odm_orthophoto/odm_orthophoto.tif"
            member = preferred if preferred in members else next(
                (name for name in members if name.endswith("/odm_orthophoto.tif") or name.endswith("odm_orthophoto.tif")),
                None,
            )
            if member is None:
                raise OrthomosaicRunError("NodeODM output did not include odm_orthophoto.tif.")
            with archive.open(member) as source, output_path.open("wb") as target:
                shutil.copyfileobj(source, target)
    except zipfile.BadZipFile as exc:
        raise OrthomosaicRunError("NodeODM returned an invalid output zip.") from exc
    return output_path


def _nodeodm_options(options_json: dict) -> list[dict[str, object]]:
    merged: dict[str, object] = {}
    if options_json.get("low_memory_preset"):
        merged.update(LOW_MEMORY_NODEODM_OPTIONS)
    for key, value in options_json.items():
        if key in APP_ONLY_OPTIONS or value is None or value == "":
            continue
        merged[key] = value
    return [{"name": key, "value": value} for key, value in merged.items()]


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _mime_type(path: Path) -> str:
    if path.suffix.lower() in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if path.suffix.lower() == ".png":
        return "image/png"
    if path.suffix.lower() in {".tif", ".tiff"}:
        return "image/tiff"
    return "application/octet-stream"


def _safe_filename(filename: str, suffix: str) -> str:
    stem = Path(filename or "image").stem[:120]
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in stem).strip("._-")
    return f"{safe or 'image'}{suffix}"
