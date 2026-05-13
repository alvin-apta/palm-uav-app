from __future__ import annotations

from math import cos, radians, sqrt


def approximate_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    mean_lat = radians((lat1 + lat2) / 2.0)
    dy = (lat2 - lat1) * 111_320.0
    dx = (lon2 - lon1) * 111_320.0 * cos(mean_lat)
    return sqrt(dx * dx + dy * dy)


def dbscan_clusters(points: list[tuple[str, float, float]], eps_m: float = 3.0, min_points: int = 1) -> list[list[str]]:
    visited: set[str] = set()
    clustered: set[str] = set()
    by_id = {point_id: (lat, lon) for point_id, lat, lon in points}
    clusters: list[list[str]] = []

    def neighbors(point_id: str) -> list[str]:
        origin = by_id[point_id]
        return [candidate_id for candidate_id, coords in by_id.items() if approximate_distance_m(origin, coords) <= eps_m]

    for point_id, _, _ in points:
        if point_id in visited:
            continue
        visited.add(point_id)
        seeds = neighbors(point_id)
        if len(seeds) < min_points:
            clusters.append([point_id])
            clustered.add(point_id)
            continue
        cluster: list[str] = []
        queue = list(seeds)
        while queue:
            candidate_id = queue.pop(0)
            if candidate_id not in visited:
                visited.add(candidate_id)
                candidate_neighbors = neighbors(candidate_id)
                if len(candidate_neighbors) >= min_points:
                    for neighbor_id in candidate_neighbors:
                        if neighbor_id not in queue:
                            queue.append(neighbor_id)
            if candidate_id not in clustered:
                clustered.add(candidate_id)
                cluster.append(candidate_id)
        clusters.append(cluster)
    return clusters

