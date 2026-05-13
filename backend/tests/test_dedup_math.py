from __future__ import annotations

from app.services.dedup_math import approximate_distance_m, dbscan_clusters


def test_approximate_distance_m_for_nearby_points() -> None:
    distance = approximate_distance_m((0.0, 101.0), (0.0, 101.00001))
    assert 1.0 < distance < 1.2


def test_dbscan_clusters_with_three_meter_radius() -> None:
    points = [
        ("a", 0.0, 101.0),
        ("b", 0.0, 101.00001),
        ("c", 0.0, 101.001),
    ]
    clusters = [set(cluster) for cluster in dbscan_clusters(points, eps_m=3.0)]
    assert {"a", "b"} in clusters
    assert {"c"} in clusters

