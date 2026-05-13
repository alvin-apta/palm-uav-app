from __future__ import annotations

from app.core.config import settings
from app.worker.orthomosaic import run_orthomosaic_job
from app.worker.inference import run_inference_job
from app.worker.queue import redis_settings_from_url


class WorkerSettings:
    functions = [run_inference_job, run_orthomosaic_job]
    redis_settings = redis_settings_from_url(settings.redis_url)
    max_jobs = 1
    job_timeout = max(60 * 60, settings.odm_timeout_seconds + 600)
