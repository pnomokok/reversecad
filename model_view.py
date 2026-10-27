"""The measurement table as the language model sees it, and as candidates are checked against.

The measurement table itself is not changed. For the model, the outline is the
simplified one (least-squares edges, torn edges flattened; see
part_measurements.least_squares_outline), round parts of it (notches, rounded
corners) are given as arcs with a center and radius instead of extra corners,
and every coordinate is re-centered on the outline's bounding box, so a
candidate centered the usual way lines up with it. Holes keep all their measured
fields here; the prompt shows only the fields each hole shape needs.
"""
import copy
import math

import numpy as np

ARC_MAX_RESIDUAL_MM = 0.3  # contour points must lie this close to the fitted circle
ARC_MIN_SPAN_DEG = 45  # a 90-degree fillet's chord between approxPolyDP corners covered 56-68 degrees
ARC_MAX_EDGES = 6  # an arc replaces at most this many consecutive simplified edges (a semicircle took 4)


def fit_circle(points):
    """Least-squares (Kasa) circle: (center, radius, rms residual, swept angle in degrees)."""
    x, y = points[:, 0], points[:, 1]
    d, e, f = np.linalg.lstsq(np.column_stack([x, y, np.ones_like(x)]), -(x**2 + y**2), rcond=None)[0]
    center = np.array([-d / 2, -e / 2])
    radius = math.sqrt(max(center @ center - f, 0.0))
    residual = float(np.sqrt(np.mean((np.hypot(x - center[0], y - center[1]) - radius) ** 2)))
    angles = np.unwrap(np.arctan2(y - center[1], x - center[0]))
    return center, radius, residual, math.degrees(abs(angles[-1] - angles[0]))


def resample(contour, step_mm=0.2):
    """Points every step_mm along the closed polyline (contour_mm keeps only a few points per small arc)."""
    closed = np.vstack([contour, contour[:1]])
    points = []
    for a, b in zip(closed[:-1], closed[1:]):
        count = max(1, int(np.ceil(np.linalg.norm(b - a) / step_mm)))
        points.extend(a + (b - a) * t for t in np.arange(count) / count)
    return np.array(points)


def _contour_between(contour, start, end):
    return contour[start:end + 1] if end >= start else np.vstack([contour[start:], contour[:end + 1]])


def find_arcs(corners, contour, max_radius_mm):
    """Runs of consecutive outline edges whose contour points form a circular arc.

    Returns (corner indices kept, arcs) where each arc is {"from": i, "to": j, "center", "radius"}
    with i and j indices into the kept corners.
    """
    count = len(corners)
    nearest = [int(np.argmin(np.linalg.norm(contour - c, axis=1))) for c in corners]
    used_edges, arcs = set(), []  # edge k runs from corner k to corner k+1; each edge joins at most one arc
    for edges in range(ARC_MAX_EDGES, 0, -1):  # longest arcs first
        for start in range(count):
            run = [(start + k) % count for k in range(edges)]
            if count - (edges - 1) < 3 or any(edge in used_edges for edge in run):
                continue
            end = (start + edges) % count
            points = _contour_between(contour, nearest[start], nearest[end])
            if len(points) < 6:
                continue
            center, radius, residual, swept = fit_circle(points)
            if residual <= ARC_MAX_RESIDUAL_MM and swept >= ARC_MIN_SPAN_DEG and radius <= max_radius_mm:
                arcs.append({"from": start, "to": end, "center": center, "radius": radius,
                             "inner": [(start + k) % count for k in range(1, edges)]})
                used_edges.update(run)
    removed = {i for arc in arcs for i in arc["inner"]}
    kept = [i for i in range(count) if i not in removed]
    position = {old: new for new, old in enumerate(kept)}
    result = []
    for arc in arcs:
        result.append({"from": position[arc["from"]], "to": position[arc["to"]],
                       "center": arc["center"], "radius": arc["radius"]})
    return kept, result


def arc_points(start, end, center, radius, steps=12):
    """Points along the shorter arc from start to end (both projected onto the circle)."""
    a0 = math.atan2(start[1] - center[1], start[0] - center[0])
    a1 = math.atan2(end[1] - center[1], end[0] - center[0])
    sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    angles = a0 + np.linspace(0, sweep, steps)
    return np.column_stack([center[0] + radius * np.cos(angles), center[1] + radius * np.sin(angles)])


def model_view(table):
    polygon = np.array(table["outline"]["simplified_polygon_mm"], dtype=float)
    contour = resample(np.array(table["outline"]["contour_mm"], dtype=float))
    kept, arcs = find_arcs(polygon, contour, max_radius_mm=table["outline"]["width_mm"] / 2)
    corners = polygon[kept]
    for arc in arcs:  # arc ends sit on the circle
        for key in ("from", "to"):
            offset = corners[arc[key]] - arc["center"]
            corners[arc[key]] = arc["center"] + offset / np.linalg.norm(offset) * arc["radius"]

    low, high = corners.min(axis=0), corners.max(axis=0)
    center = (low + high) / 2

    def shift(point):
        return [round(float(point[0] - center[0]), 2), round(float(point[1] - center[1]), 2)]

    holes = []
    for hole in table["holes"]:
        hole = copy.deepcopy(hole)
        hole["center_from_part_center_mm"] = shift(hole["center_from_part_center_mm"])
        if "polygon_mm" in hole:
            hole["polygon_mm"] = [shift(p) for p in hole["polygon_mm"]]
        holes.append(hole)
    return {
        "outline": {
            "length_mm": round(float(high[0] - low[0]), 2),
            "width_mm": round(float(high[1] - low[1]), 2),
            "vertex_count": len(corners),
            "polygon_mm": [shift(p) for p in corners],
            # the edge from corner `from` to corner `to` (indices into polygon_mm) is this arc, not a line
            "arcs": [{"from": arc["from"], "to": arc["to"], "center_mm": shift(arc["center"]),
                      "radius_mm": round(float(arc["radius"]), 2)} for arc in arcs],
        },
        "hole_count": len(holes),
        "holes": holes,
    }
