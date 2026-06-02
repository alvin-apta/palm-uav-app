from __future__ import annotations

from alembic import op
import geoalchemy2
import sqlalchemy as sa


revision = "0004_block_areas"
down_revision = "0003_canopy_size_classes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "block_areas",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("blocks.id"), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("geom", geoalchemy2.Geometry("MULTIPOLYGON", srid=4326), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_block_areas_block_id", "block_areas", ["block_id"])


def downgrade() -> None:
    op.drop_index("ix_block_areas_block_id", table_name="block_areas")
    op.drop_table("block_areas")
