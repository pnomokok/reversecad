"""How far may a candidate's clean design values stray from the measurements?

Candidates may replace irregular measured edges (torn, hand-cut) with the clean
shape a designer meant, but every dimension must stay within max(1 mm, 2% of
that dimension) of the measurement table; a candidate that strays further is
rejected. Hole positions use 2% of the part's length. Each check produces a row
with the measured value, the candidate's value, the deviation and the limit,
so the report can show them side by side.
"""
from part_measurements import match_holes

MIN_TOLERANCE_MM = 1.0
RELATIVE_TOLERANCE = 0.02


def tolerance(size_mm):
    return max(MIN_TOLERANCE_MM, RELATIVE_TOLERANCE * abs(size_mm))


def _hole_sizes(hole):
    if hole["shape"] == "circle":
        return {"diameter": hole["diameter_mm"]}
    return {"length": hole["length_mm"], "width": hole["width_mm"]}  # bounding size for polygons


def check_deviation(measured, candidate):
    """Return (ok, rows) comparing a candidate's rendered table with the measured table."""
    rows = []

    def add(name, measured_value, candidate_value, limit):
        deviation = candidate_value - measured_value
        rows.append({"dimension": name, "measured_mm": round(measured_value, 2),
                     "candidate_mm": round(candidate_value, 2), "deviation_mm": round(deviation, 2),
                     "limit_mm": round(limit, 2), "ok": abs(deviation) <= limit})

    for key in ("length_mm", "width_mm"):
        add(f"outline {key[:-3]}", measured["outline"][key], candidate["outline"][key],
            tolerance(measured["outline"][key]))
    if candidate["hole_count"] != measured["hole_count"]:
        rows.append({"dimension": "hole count", "measured_mm": measured["hole_count"],
                     "candidate_mm": candidate["hole_count"], "deviation_mm": None, "limit_mm": 0, "ok": False})
    position_limit = tolerance(measured["outline"]["length_mm"])
    for i, match in enumerate(match_holes(candidate["holes"], measured["holes"]), 1):
        hole, chosen = match["truth"], match["measured"]  # here "truth" is the measured table
        if chosen is None:
            continue  # already counted in the hole-count row
        rows.append({"dimension": f"hole {i} position", "measured_mm": hole["center_from_part_center_mm"],
                     "candidate_mm": chosen["center_from_part_center_mm"],
                     "deviation_mm": match["center_error_mm"], "limit_mm": round(position_limit, 2),
                     "ok": match["center_error_mm"] <= position_limit})
        measured_sizes, chosen_sizes = _hole_sizes(hole), _hole_sizes(chosen)
        if set(measured_sizes) != set(chosen_sizes):  # circle vs elongated: compare equal-area diameters
            measured_sizes, chosen_sizes = {"diameter": hole["diameter_mm"]}, {"diameter": chosen["diameter_mm"]}
        for key, value in measured_sizes.items():
            add(f"hole {i} {key}", value, chosen_sizes[key], tolerance(value))
    return all(row["ok"] for row in rows), rows
