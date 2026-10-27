"""How far may a candidate's clean design values stray from the measurements?

Candidates may replace irregular measured edges (torn, hand-cut) with the clean
shape a designer meant, within these limits of the model's view of the table
(model_view.py):
- outline length and width: max(1 mm, 2% of the dimension) (0.5 mm if under 20 mm);
- holes, size and position: 0.5 mm;
- outline corners: each corner the model was shown must lie within the limit of
  the candidate's outline; 0.5 mm for corners of features with an edge shorter
  than 20 mm (tabs, notches), else the outline limit.
A candidate that strays further is rejected. Each check produces a row with the
measured value, the candidate's value, the deviation and the limit, so the
report can show them side by side.
"""
import numpy as np

from part_measurements import FLIPS, match_holes

SMALL_FEATURE_MM = 20.0
SMALL_LIMIT_MM = 0.5


def tolerance(size_mm):
    if abs(size_mm) < SMALL_FEATURE_MM:
        return SMALL_LIMIT_MM
    return max(1.0, 0.02 * abs(size_mm))


def _hole_sizes(hole):
    if hole["shape"] == "circle":
        return {"diameter": hole["diameter_mm"]}
    return {"length": hole["length_mm"], "width": hole["width_mm"]}  # bounding size for polygons


def _distances_to_outline(points, outline):
    """Distance from each point to the closed polyline `outline`."""
    a = np.asarray(outline, dtype=float)
    b = np.roll(a, -1, axis=0)
    ab = b - a
    lengths = np.maximum((ab**2).sum(axis=1), 1e-12)
    result = []
    for p in np.asarray(points, dtype=float):
        t = np.clip(((p - a) * ab).sum(axis=1) / lengths, 0, 1)
        result.append(float(np.min(np.linalg.norm(a + t[:, None] * ab - p, axis=1))))
    return np.array(result)


def _corner_limits(polygon, width_mm):
    """Per corner: 0.5 mm if an adjacent edge is shorter than 20 mm, else the outline limit."""
    polygon = np.asarray(polygon, dtype=float)
    edges = np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)
    shortest = np.minimum(edges, np.roll(edges, 1))  # edge after and edge before each corner
    return np.where(shortest < SMALL_FEATURE_MM, SMALL_LIMIT_MM, max(1.0, 0.02 * width_mm))


def check_deviation(view, candidate):
    """Return (ok, rows) comparing a candidate's rendered table with the model's view of the table."""
    rows = []

    def add(name, measured_value, candidate_value, limit):
        deviation = candidate_value - measured_value
        rows.append({"dimension": name, "measured_mm": round(measured_value, 2),
                     "candidate_mm": round(candidate_value, 2), "deviation_mm": round(deviation, 2),
                     "limit_mm": round(limit, 2), "ok": abs(deviation) <= limit})

    for key in ("length_mm", "width_mm"):
        add(f"outline {key[:-3]}", view["outline"][key], candidate["outline"][key], tolerance(view["outline"][key]))

    # Outline corners, in whichever mirror orientation fits the candidate best.
    corners = np.array(view["outline"]["polygon_mm"], dtype=float)
    limits = _corner_limits(corners, view["outline"]["width_mm"])
    distances = min((_distances_to_outline(corners * np.array(flip), candidate["outline"]["contour_mm"])
                     for flip in FLIPS), key=lambda d: float(np.sum(d / limits)))
    for i, (corner, distance, limit) in enumerate(zip(corners, distances, limits), 1):
        rows.append({"dimension": f"corner {i}", "measured_mm": [round(float(c), 2) for c in corner],
                     "candidate_mm": "on outline" if distance <= limit else "off outline",
                     "deviation_mm": round(float(distance), 2), "limit_mm": round(float(limit), 2),
                     "ok": bool(distance <= limit)})

    if candidate["hole_count"] != view["hole_count"]:
        rows.append({"dimension": "hole count", "measured_mm": view["hole_count"],
                     "candidate_mm": candidate["hole_count"], "deviation_mm": None, "limit_mm": 0, "ok": False})
    for i, match in enumerate(match_holes(candidate["holes"], view["holes"]), 1):
        hole, chosen = match["truth"], match["measured"]  # here "truth" is the model's view of the table
        if chosen is None:
            continue  # already counted in the hole-count row
        rows.append({"dimension": f"hole {i} position", "measured_mm": hole["center_from_part_center_mm"],
                     "candidate_mm": chosen["center_from_part_center_mm"],
                     "deviation_mm": match["center_error_mm"], "limit_mm": SMALL_LIMIT_MM,
                     "ok": match["center_error_mm"] <= SMALL_LIMIT_MM})
        measured_sizes, chosen_sizes = _hole_sizes(hole), _hole_sizes(chosen)
        if set(measured_sizes) != set(chosen_sizes):  # circle vs elongated: compare equal-area diameters
            measured_sizes, chosen_sizes = {"diameter": hole["diameter_mm"]}, {"diameter": chosen["diameter_mm"]}
        for key, value in measured_sizes.items():
            add(f"hole {i} {key}", value, chosen_sizes[key], SMALL_LIMIT_MM)
    return all(row["ok"] for row in rows), rows
