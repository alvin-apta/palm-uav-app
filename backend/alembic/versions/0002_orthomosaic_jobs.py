from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002_orthomosaic_jobs"
down_revision = "0001_initial_postgis_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    job_status = postgresql.ENUM("queued", "running", "complete", "failed", name="jobstatus", create_type=False)
    op.create_table(
        "orthomosaic_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("requested_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("output_asset_id", sa.String(36), sa.ForeignKey("imagery_assets.id"), nullable=True),
        sa.Column("status", job_status, nullable=False),
        sa.Column("engine", sa.String(64), nullable=False, server_default="opendronemap"),
        sa.Column("asset_ids_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("quality_json", sa.JSON(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orthomosaic_jobs_block_id", "orthomosaic_jobs", ["block_id"])


def downgrade() -> None:
    op.drop_index("ix_orthomosaic_jobs_block_id", table_name="orthomosaic_jobs")
    op.drop_table("orthomosaic_jobs")
