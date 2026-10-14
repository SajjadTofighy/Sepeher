"""Pure local geometry in metres; coordinates are always [longitude, latitude]."""

import math

from ..sim import EARTH_RADIUS_M, distance_km


def project_m(point, reference_lat, reference_lon=0):
    """Local equirectangular coordinates, centred on the supplied reference."""
    return (
        EARTH_RADIUS_M * math.radians(point[0] - reference_lon) * math.cos(math.radians(reference_lat)),
        EARTH_RADIUS_M * math.radians(point[1] - reference_lat),
    )


def _segment_projection(point, a, b):
    reference_lat = (a[1] + b[1]) / 2
    p, start, end = [project_m(v, reference_lat, a[0]) for v in (point, a, b)]
    dx, dy = end[0] - start[0], end[1] - start[1]
    squared = dx * dx + dy * dy
    t = max(0, min(1, ((p[0] - start[0]) * dx + (p[1] - start[1]) * dy) / squared)) if squared else 0
    return p, start, dx, dy, t


def point_segment_distance_m(point, a, b):
    p, start, dx, dy, t = _segment_projection(point, a, b)
    return math.hypot(p[0] - start[0] - t * dx, p[1] - start[1] - t * dy)


def closest_segment_point(point, a, b):
    _, _, _, _, t = _segment_projection(point, a, b)
    return [a[i] + t * (b[i] - a[i]) for i in (0, 1)]


def hazard_contains(point, area):
    from ..engine import point_in_polygon

    if area["type"] == "circle":
        return distance_km(point, area["center"]) * 1000 <= area["radius_m"]
    points = area["points"]
    return (point_in_polygon(*point, points)
            or point_polyline_distance_m(point, points + [points[0]]) <= 1e-6)


def hazard_boundary_distance_m(point, area):
    if area["type"] == "circle":
        return abs(distance_km(point, area["center"]) * 1000 - area["radius_m"])
    points = area["points"]
    return point_polyline_distance_m(point, points + [points[0]])


def closest_hazard_boundary(point, area):
    if area["type"] == "polygon":
        points = area["points"] + [area["points"][0]]
        a, b = min(zip(points, points[1:]), key=lambda leg: point_segment_distance_m(point, *leg))
        return closest_segment_point(point, a, b)
    center = area["center"]
    # Destination on the circle at the great-circle bearing toward the patrol.
    lon1, lat1, lon2, lat2 = map(math.radians, [*center, *point])
    bearing = math.atan2(math.sin(lon2 - lon1) * math.cos(lat2),
                         math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))
    angle = area["radius_m"] / EARTH_RADIUS_M
    lat = math.asin(math.sin(lat1) * math.cos(angle) + math.cos(lat1) * math.sin(angle) * math.cos(bearing))
    lon = lon1 + math.atan2(math.sin(bearing) * math.sin(angle) * math.cos(lat1), math.cos(angle) - math.sin(lat1) * math.sin(lat))
    return [(math.degrees(lon) + 180) % 360 - 180, math.degrees(lat)]


def point_polyline_distance_m(point, points):
    if not points:
        return math.inf
    if len(points) == 1:
        return point_segment_distance_m(point, points[0], points[0])
    return min(point_segment_distance_m(point, a, b) for a, b in zip(points, points[1:]))


def point_at_chainage(points, chainage_m):
    """A coordinate on a configured line, measured along its bends in metres."""
    lengths = [distance_km(a, b) for a, b in zip(points, points[1:])]
    remaining = chainage_m / 1000
    for a, b, length in zip(points, points[1:], lengths):
        if length and remaining <= length:
            return [a[i] + (b[i] - a[i]) * remaining / length for i in (0, 1)]
        remaining -= length
    return list(points[-1])


def polyline_midpoint(points):
    """A target on the line, halfway along its length, including bends."""
    length_m = sum(distance_km(a, b) * 1000 for a, b in zip(points, points[1:]))
    return point_at_chainage(points, length_m / 2)


def densify(a, b, step_m):
    """Include both endpoints, with intermediate GPS coordinates at most step_m apart."""
    if not math.isfinite(step_m) or step_m <= 0:
        raise ValueError("step_m must be positive and finite")
    pieces = max(1, math.ceil(distance_km(a, b) * 1000 / step_m))
    return [[a[i] + (b[i] - a[i]) * k / pieces for i in (0, 1)] for k in range(pieces + 1)]


def bbox(points):
    if not points:
        raise ValueError("bbox requires at least one point")
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def expand_bbox(bounds, margin_m):
    if not math.isfinite(margin_m) or margin_m < 0:
        raise ValueError("margin_m must be nonnegative and finite")
    reference_lat = max(abs(bounds[1]), abs(bounds[3]))
    dy = math.degrees(margin_m / EARTH_RADIUS_M)
    dx = dy / math.cos(math.radians(reference_lat))
    return (bounds[0] - dx, bounds[1] - dy, bounds[2] + dx, bounds[3] + dy)


def bbox_contains(bounds, point):
    return bounds[0] <= point[0] <= bounds[2] and bounds[1] <= point[1] <= bounds[3]


def bboxes_intersect(a, b):
    return a[0] <= b[2] and a[2] >= b[0] and a[1] <= b[3] and a[3] >= b[1]


def derive_segments(pipelines, step_m=500):
    """Split along each pipeline, retaining bends and deriving stable segment IDs."""
    if not math.isfinite(step_m) or step_m <= 0:
        raise ValueError("step_m must be positive and finite")
    segments = []
    for pipeline in pipelines:
        piece, length, index = [list(pipeline["points"][0])], 0.0, 0

        def emit():
            nonlocal piece, length, index
            access = {key: pipeline.get(key) for key in ("road_distance_m", "village_distance_m", "heavy_vehicle_access") if key in pipeline}
            segments.append(dict(**access, id=f"{pipeline['id']}-SEG-{index:04}", pipeline_id=pipeline["id"],
                                 index=index, points=piece, length_m=length, field=pipeline["field"]))
            piece, length, index = [piece[-1]], 0.0, index + 1

        for endpoint in pipeline["points"][1:]:
            endpoint = list(endpoint)
            remaining = distance_km(piece[-1], endpoint) * 1000
            while remaining > 1e-6:
                available = step_m - length
                if remaining <= available + 1e-6:
                    piece.append(endpoint)
                    length += remaining
                    if length >= step_m - 1e-6:
                        emit()
                    break
                fraction = available / remaining
                start = piece[-1]
                piece.append([start[i] + (endpoint[i] - start[i]) * fraction for i in (0, 1)])
                length += distance_km(start, piece[-1]) * 1000
                emit()
                remaining = distance_km(piece[-1], endpoint) * 1000
        if length > 1e-6:
            emit()
    return segments
