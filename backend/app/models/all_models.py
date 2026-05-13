from __future__ import annotations

import enum
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def uuid_str() -> str:
    return str(uuid.uuid4())


class UserRole(str, enum.Enum):
    owner = "owner"
    manager = "manager"
    operator = "operator"


class HealthClass(str, enum.Enum):
    healthy = "healthy"
    yellow_stressed = "yellow_stressed"
    small_young = "small_young"
    dead = "dead"


class AssetType(str, enum.Enum):
    photo = "photo"
    cog = "cog"
    dsm = "dsm"
    dtm = "dtm"
    road = "road"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    complete = "complete"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False, default=UserRole.operator)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Estate(Base):
    __tablename__ = "estates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    blocks: Mapped[list["Block"]] = relationship(back_populates="estate", cascade="all, delete-orphan")


class Block(Base):
    __tablename__ = "blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    estate_id: Mapped[str] = mapped_column(ForeignKey("estates.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    planting_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    palm_spacing_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_palms_ha: Mapped[float | None] = mapped_column(Float, nullable=True)
    boundary: Mapped[object | None] = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    estate: Mapped[Estate] = relationship(back_populates="blocks")
    trees: Mapped[list["Tree"]] = relationship(back_populates="block")

    __table_args__ = (UniqueConstraint("estate_id", "name", name="uq_blocks_estate_name"),)


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    mission_type: Mapped[str] = mapped_column(String(64), nullable=False, default="inventory")
    pilot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    drone_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    route_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ImageryAsset(Base):
    __tablename__ = "imagery_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    cog_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    width_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height_px: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    sensor_width_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    focal_length_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class InferenceJob(Base):
    __tablename__ = "inference_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.queued)
    model_weights_path: Mapped[str] = mapped_column(Text, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    asset_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrthomosaicJob(Base):
    __tablename__ = "orthomosaic_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    requested_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    output_asset_id: Mapped[str | None] = mapped_column(ForeignKey("imagery_assets.id"), nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), nullable=False, default=JobStatus.queued)
    engine: Mapped[str] = mapped_column(String(64), nullable=False, default="nodeodm")
    asset_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    options_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quality_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DetectionRaw(Base):
    __tablename__ = "detections_raw"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    job_id: Mapped[str] = mapped_column(ForeignKey("inference_jobs.id"), nullable=False, index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("imagery_assets.id"), nullable=True, index=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    health_class: Mapped[HealthClass] = mapped_column(Enum(HealthClass), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    pixel_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    pixel_y: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    geom: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326), nullable=True, index=True)
    canopy_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    vari: Mapped[float | None] = mapped_column(Float, nullable=True)
    lai_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Tree(Base):
    __tablename__ = "trees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326), nullable=False, index=True)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    health_class: Mapped[HealthClass] = mapped_column(Enum(HealthClass), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    canopy_area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    equivalent_diameter_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    vari: Mapped[float | None] = mapped_column(Float, nullable=True)
    chm_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    lai_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    latest_observation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    block: Mapped[Block] = relationship(back_populates="trees")


class TreeObservation(Base):
    __tablename__ = "tree_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    tree_id: Mapped[str] = mapped_column(ForeignKey("trees.id"), nullable=False, index=True)
    detection_id: Mapped[str] = mapped_column(ForeignKey("detections_raw.id"), nullable=False, index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("inference_jobs.id"), nullable=False, index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PrescriptionMap(Base):
    __tablename__ = "prescription_maps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    created_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    format_bundle_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class FieldTask(Base):
    __tablename__ = "field_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    tree_id: Mapped[str | None] = mapped_column(ForeignKey("trees.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AccessRoad(Base):
    __tablename__ = "access_roads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid_str)
    block_id: Mapped[str] = mapped_column(ForeignKey("blocks.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    geom: Mapped[object] = mapped_column(Geometry("LINESTRING", srid=4326), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
