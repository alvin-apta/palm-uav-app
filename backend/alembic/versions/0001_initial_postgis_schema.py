from __future__ import annotations

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_postgis_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.execute(
        """
        DO $$
        BEGIN
            CREATE TYPE userrole AS ENUM ('owner', 'manager', 'operator');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$
        BEGIN
            CREATE TYPE healthclass AS ENUM ('small_canopy', 'medium_canopy', 'large_canopy');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$
        BEGIN
            CREATE TYPE assettype AS ENUM ('photo', 'cog', 'dsm', 'dtm', 'road');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        DO $$
        BEGIN
            CREATE TYPE jobstatus AS ENUM ('queued', 'running', 'complete', 'failed');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    user_role = postgresql.ENUM("owner", "manager", "operator", name="userrole", create_type=False)
    health_class = postgresql.ENUM("small_canopy", "medium_canopy", "large_canopy", name="healthclass", create_type=False)
    asset_type = postgresql.ENUM("photo", "cog", "dsm", "dtm", "road", name="assettype", create_type=False)
    job_status = postgresql.ENUM("queued", "running", "complete", "failed", name="jobstatus", create_type=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "estates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("estate_id", sa.String(36), sa.ForeignKey("estates.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("planting_year", sa.Integer(), nullable=True),
        sa.Column("palm_spacing_m", sa.Float(), nullable=True),
        sa.Column("target_palms_ha", sa.Float(), nullable=True),
        sa.Column("boundary", geoalchemy2.Geometry("POLYGON", srid=4326), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("estate_id", "name", name="uq_blocks_estate_name"),
    )
    op.create_index("ix_blocks_estate_id", "blocks", ["estate_id"])

    op.create_table(
        "missions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("mission_type", sa.String(64), nullable=False),
        sa.Column("pilot", sa.String(255), nullable=True),
        sa.Column("drone_name", sa.String(255), nullable=True),
        sa.Column("route_notes", sa.Text(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_missions_block_id", "missions", ["block_id"])

    op.create_table(
        "imagery_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("asset_type", asset_type, nullable=False),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("cog_url", sa.Text(), nullable=True),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("gps_lat", sa.Float(), nullable=True),
        sa.Column("gps_lon", sa.Float(), nullable=True),
        sa.Column("altitude_m", sa.Float(), nullable=True),
        sa.Column("heading_deg", sa.Float(), nullable=True),
        sa.Column("sensor_width_mm", sa.Float(), nullable=True),
        sa.Column("focal_length_mm", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_imagery_assets_block_id", "imagery_assets", ["block_id"])

    op.create_table(
        "inference_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", job_status, nullable=False),
        sa.Column("model_weights_path", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inference_jobs_block_id", "inference_jobs", ["block_id"])

    op.create_table(
        "detections_raw",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("inference_jobs.id"), nullable=False),
        sa.Column("asset_id", sa.String(36), sa.ForeignKey("imagery_assets.id"), nullable=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("health_class", health_class, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("bbox_json", sa.JSON(), nullable=False),
        sa.Column("pixel_x", sa.Float(), nullable=True),
        sa.Column("pixel_y", sa.Float(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=True),
        sa.Column("canopy_area_m2", sa.Float(), nullable=True),
        sa.Column("vari", sa.Float(), nullable=True),
        sa.Column("lai_estimate", sa.Float(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_detections_raw_job_id", "detections_raw", ["job_id"])
    op.create_index("ix_detections_raw_asset_id", "detections_raw", ["asset_id"])
    op.create_index("ix_detections_raw_block_id", "detections_raw", ["block_id"])

    op.create_table(
        "trees",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("POINT", srid=4326), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("health_class", health_class, nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("canopy_area_m2", sa.Float(), nullable=True),
        sa.Column("equivalent_diameter_m", sa.Float(), nullable=True),
        sa.Column("vari", sa.Float(), nullable=True),
        sa.Column("chm_m", sa.Float(), nullable=True),
        sa.Column("lai_estimate", sa.Float(), nullable=True),
        sa.Column("latest_observation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_trees_block_id", "trees", ["block_id"])

    op.create_table(
        "tree_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tree_id", sa.String(36), sa.ForeignKey("trees.id"), nullable=False),
        sa.Column("detection_id", sa.String(36), sa.ForeignKey("detections_raw.id"), nullable=False),
        sa.Column("job_id", sa.String(36), sa.ForeignKey("inference_jobs.id"), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tree_observations_tree_id", "tree_observations", ["tree_id"])
    op.create_index("ix_tree_observations_detection_id", "tree_observations", ["detection_id"])
    op.create_index("ix_tree_observations_job_id", "tree_observations", ["job_id"])

    op.create_table(
        "prescription_maps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("format_bundle_path", sa.Text(), nullable=True),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_prescription_maps_block_id", "prescription_maps", ["block_id"])

    op.create_table(
        "field_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("tree_id", sa.String(36), sa.ForeignKey("trees.id"), nullable=True),
        sa.Column("task_type", sa.String(128), nullable=False),
        sa.Column("priority", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_field_tasks_block_id", "field_tasks", ["block_id"])
    op.create_index("ix_field_tasks_tree_id", "field_tasks", ["tree_id"])

    op.create_table(
        "access_roads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("LINESTRING", srid=4326), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_access_roads_block_id", "access_roads", ["block_id"])


def downgrade() -> None:
    op.drop_table("access_roads")
    op.drop_table("field_tasks")
    op.drop_table("prescription_maps")
    op.drop_table("tree_observations")
    op.drop_table("trees")
    op.drop_table("detections_raw")
    op.drop_table("inference_jobs")
    op.drop_table("imagery_assets")
    op.drop_table("missions")
    op.drop_table("blocks")
    op.drop_table("estates")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS assettype")
    op.execute("DROP TYPE IF EXISTS healthclass")
    op.execute("DROP TYPE IF EXISTS userrole")
