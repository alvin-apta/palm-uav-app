"""switch health classes to canopy size classes

Revision ID: 0003_canopy_size_classes
Revises: 0002_orthomosaic_jobs
Create Date: 2026-05-19
"""

from __future__ import annotations

from alembic import op


revision = "0003_canopy_size_classes"
down_revision = "0002_orthomosaic_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE healthclass RENAME TO healthclass_old")
    op.execute("CREATE TYPE healthclass AS ENUM ('small_canopy', 'medium_canopy', 'large_canopy')")
    for table in ("detections_raw", "trees"):
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN health_class TYPE healthclass
            USING (
                CASE
                    WHEN canopy_area_m2 IS NOT NULL AND sqrt(4 * canopy_area_m2 / pi()) < 6.0 THEN 'small_canopy'
                    WHEN canopy_area_m2 IS NOT NULL AND sqrt(4 * canopy_area_m2 / pi()) >= 10.0 THEN 'large_canopy'
                    WHEN canopy_area_m2 IS NOT NULL THEN 'medium_canopy'
                    ELSE CASE health_class::text
                    WHEN 'small_young' THEN 'small_canopy'
                    ELSE 'medium_canopy'
                    END
                END
            )::healthclass
            """
        )
    op.execute("DROP TYPE healthclass_old")


def downgrade() -> None:
    op.execute("ALTER TYPE healthclass RENAME TO healthclass_new")
    op.execute("CREATE TYPE healthclass AS ENUM ('healthy', 'yellow_stressed', 'small_young', 'dead')")
    for table in ("detections_raw", "trees"):
        op.execute(
            f"""
            ALTER TABLE {table}
            ALTER COLUMN health_class TYPE healthclass
            USING (
                CASE health_class::text
                    WHEN 'small_canopy' THEN 'small_young'
                    ELSE 'healthy'
                END
            )::healthclass
            """
        )
    op.execute("DROP TYPE healthclass_new")
