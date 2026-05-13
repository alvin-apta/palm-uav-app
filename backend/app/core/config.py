from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PalmOps Web-GIS"
    environment: str = "local"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    secret_key: str = Field(default="change-this-secret-before-production")
    access_token_expire_minutes: int = 720

    database_url: str = "postgresql+psycopg://palmops:palmops@postgres:5432/palmops"
    redis_url: str = "redis://redis:6379/0"

    data_dir: Path = Path("/data")
    model_weights_path: Path = Path("/models/palm_health.pt")
    yolo_confidence: float = 0.01
    yolo_iou: float = 0.45
    roboflow_api_key: str = ""
    roboflow_model_id: str = "oil-palm-tree-health-detection/1"
    roboflow_confidence: int = 35
    roboflow_overlap: int = 30
    roboflow_max_image_side: int = 1600
    odm_command_template: str = ""
    odm_timeout_seconds: int = 60 * 60 * 6
    nodeodm_url: str = "http://nodeodm:3000"
    nodeodm_poll_interval_seconds: int = 10
    stitch_min_images: int = 5
    titiler_base_url: str = "http://localhost:8081"
    public_api_base_url: str = "http://localhost:8080"
    public_titiler_base_url: str = "http://localhost:8081"

    default_owner_email: str = "owner@example.com"
    default_owner_password: str = "palmops123"

    allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
    ]

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def odm_project_dir(self) -> Path:
        return self.data_dir / "odm_projects"


settings = Settings()
