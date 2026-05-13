from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import settings


def redis_settings_from_url(url: str) -> RedisSettings:
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "redis",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or "0"),
        password=parsed.password,
    )


async def enqueue_inference(job_id: str) -> None:
    redis = await create_pool(redis_settings_from_url(settings.redis_url))
    try:
        await redis.enqueue_job("run_inference_job", job_id)
    finally:
        await redis.close()


async def enqueue_orthomosaic(job_id: str) -> None:
    redis = await create_pool(redis_settings_from_url(settings.redis_url))
    try:
        await redis.enqueue_job("run_orthomosaic_job", job_id)
    finally:
        await redis.close()
