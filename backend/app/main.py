from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import analytics, auth, blocks, exports, imagery, jobs, map, missions, orthomosaics, spatial
from app.core.config import settings
from app.db.seed import ensure_seed_data
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "error": exc.__class__.__name__})

app.include_router(auth.router)
app.include_router(blocks.router)
app.include_router(missions.router)
app.include_router(imagery.router)
app.include_router(orthomosaics.router)
app.include_router(jobs.router)
app.include_router(map.router)
app.include_router(analytics.router)
app.include_router(exports.router)
app.include_router(spatial.router)


@app.on_event("startup")
def startup() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    settings.odm_project_dir.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        ensure_seed_data(db)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}
