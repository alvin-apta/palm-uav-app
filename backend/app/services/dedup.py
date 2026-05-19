from __future__ import annotations

from geoalchemy2 import WKTElement
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.all_models import Tree, TreeObservation
from app.services.analytics import equivalent_diameter


def deduplicate_job(db: Session, job_id: str, eps_m: float = 3.0) -> int:
    rows = db.execute(
        text(
            """
            WITH clustered AS (
                SELECT
                    id,
                    ST_ClusterDBSCAN(ST_Transform(geom, 3857), eps := :eps_m, minpoints := 1)
                        OVER (ORDER BY confidence DESC, id) AS cid
                FROM detections_raw
                WHERE job_id = :job_id AND geom IS NOT NULL
            )
            SELECT
                c.cid,
                d.block_id,
                array_agg(d.id ORDER BY d.confidence DESC) AS detection_ids,
                ST_Y(ST_Transform(ST_Centroid(ST_Collect(ST_Transform(d.geom, 3857))), 4326)) AS lat,
                ST_X(ST_Transform(ST_Centroid(ST_Collect(ST_Transform(d.geom, 3857))), 4326)) AS lon,
                CASE
                    WHEN avg(d.canopy_area_m2) IS NULL THEN (array_agg(d.health_class ORDER BY d.confidence DESC, d.id))[1]
                    WHEN sqrt(4 * avg(d.canopy_area_m2) / pi()) < 6.0 THEN 'small_canopy'
                    WHEN sqrt(4 * avg(d.canopy_area_m2) / pi()) >= 10.0 THEN 'large_canopy'
                    ELSE 'medium_canopy'
                END AS health_class,
                max(d.confidence) AS confidence,
                avg(d.canopy_area_m2) AS canopy_area_m2,
                avg(d.vari) AS vari,
                avg(d.lai_estimate) AS lai_estimate
            FROM clustered c
            JOIN detections_raw d ON d.id = c.id
            GROUP BY c.cid, d.block_id
            ORDER BY c.cid
            """
        ),
        {"job_id": job_id, "eps_m": eps_m},
    ).mappings()

    created = 0
    for row in rows:
        lat = float(row["lat"])
        lon = float(row["lon"])
        canopy_area = row["canopy_area_m2"]
        tree = Tree(
            block_id=row["block_id"],
            lat=lat,
            lon=lon,
            geom=WKTElement(f"POINT({lon} {lat})", srid=4326),
            health_class=row["health_class"],
            confidence=float(row["confidence"] or 0.0),
            canopy_area_m2=float(canopy_area) if canopy_area is not None else None,
            equivalent_diameter_m=equivalent_diameter(float(canopy_area)) if canopy_area is not None else None,
            vari=float(row["vari"]) if row["vari"] is not None else None,
            lai_estimate=float(row["lai_estimate"]) if row["lai_estimate"] is not None else None,
        )
        db.add(tree)
        db.flush()
        for detection_id in row["detection_ids"] or []:
            db.add(TreeObservation(tree_id=tree.id, detection_id=detection_id, job_id=job_id))
        created += 1
    db.commit()
    return created
