"""Measurement table of a flat part from its mask: outline, corners, holes (mm).

The mask's outline and holes are mapped to millimeters with a pixel-to-mm
homography. Everything is given in the part's own frame [u, v]: u along the
length of the outline's minimum-area rectangle, v along its width, origin at
that rectangle's center. Outline corners come from lines fitted to each edge
and intersected (like the card's corners). The language model gets these
numbers; it never measures pixels itself.
"""
import math

import cv2
import numpy as np

from homography import to_mm

MIN_HOLE_AREA_MM2 = 0.5  # ignore specks smaller than about 0.8 mm across
POLYGON_EPSILON_MM = 0.8  # max deviation when simplifying the outline to corners
EDGE_TRIM = 0.15  # fraction of each edge ignored at both ends when fitting its line
MAX_CORNER_SHIFT_MM = 3.0  # fall back to the simplified corner if the fitted one moves further
FLIPS = [(1, 1), (-1, 1), (1, -1), (-1, -1)]  # the part's axis has no "front"; mirroring is allowed


def _fit_line(points):
    vx, vy, x0, y0 = cv2.fitLine(points.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.array([x0, y0]), np.array([vx, vy])


def _intersect(line_a, line_b):
    (point_a, dir_a), (point_b, dir_b) = line_a, line_b
    matrix = np.column_stack([dir_a, -dir_b])
    if abs(np.linalg.det(matrix)) < 1e-6:
        return None
    s, _ = np.linalg.solve(matrix, point_b - point_a)
    return point_a + s * dir_a


def outline_polygon(contour_mm):
    """Corners of the outline: simplify, then refine each corner by intersecting fitted edge lines."""
    approx = cv2.approxPolyDP(contour_mm.reshape(-1, 1, 2).astype(np.float32), POLYGON_EPSILON_MM, True)
    approx = approx.reshape(-1, 2)
    indices = sorted(int(np.argmin(np.linalg.norm(contour_mm - p, axis=1))) for p in approx)
    count = len(indices)
    if count < 3:
        return approx.astype(np.float64)
    lines = []
    for i in range(count):
        start, end = indices[i], indices[(i + 1) % count]
        edge = contour_mm[start:end + 1] if end > start else np.vstack([contour_mm[start:], contour_mm[:end + 1]])
        trim = int(len(edge) * EDGE_TRIM)
        middle = edge[trim:len(edge) - trim] if len(edge) - 2 * trim >= 5 else edge
        lines.append(_fit_line(middle))
    corners = []
    for i in range(count):
        corner = _intersect(lines[i - 1], lines[i])  # corner i joins edge i-1 and edge i
        simple = contour_mm[indices[i]]
        if corner is None or np.linalg.norm(corner - simple) > MAX_CORNER_SHIFT_MM:
            corner = simple
        corners.append(corner)
    return np.array(corners)


def measure_part(part_mask, homography):
    """Return the measurement table as a dict (all lengths in mm)."""
    contours, hierarchy = cv2.findContours(part_mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("part mask is empty")
    parents = hierarchy[0][:, 3]
    outer_index = max((i for i in range(len(contours)) if parents[i] == -1),
                      key=lambda i: cv2.contourArea(contours[i]))
    outer_mm = to_mm(contours[outer_index].reshape(-1, 2), homography)

    (cx, cy), (w, h), angle = cv2.minAreaRect(outer_mm.astype(np.float32))
    length, width = max(w, h), min(w, h)
    axis = math.radians(angle if w >= h else angle + 90)
    cos_a, sin_a = math.cos(axis), math.sin(axis)

    def to_part_frame(x, y):
        dx, dy = x - cx, y - cy
        return [round(float(dx * cos_a + dy * sin_a), 2), round(float(-dx * sin_a + dy * cos_a), 2)]

    holes = []
    for i in range(len(contours)):
        if parents[i] != outer_index:
            continue
        hole_mm = to_mm(contours[i].reshape(-1, 2), homography).astype(np.float32)
        area = cv2.contourArea(hole_mm)
        if area < MIN_HOLE_AREA_MM2:
            continue
        moments = cv2.moments(hole_mm)
        roundness = None
        if len(hole_mm) >= 5:
            axes = cv2.fitEllipse(hole_mm)[1]
            roundness = round(float(min(axes) / max(axes)), 3)
        holes.append({
            "center_from_part_center_mm": to_part_frame(moments["m10"] / moments["m00"],
                                                        moments["m01"] / moments["m00"]),
            "diameter_mm": round(float(2 * math.sqrt(area / math.pi)), 2),
            "roundness": roundness,
        })
    holes.sort(key=lambda hole: tuple(hole["center_from_part_center_mm"]))

    corners = [to_part_frame(x, y) for x, y in outline_polygon(outer_mm)]
    return {
        "outline": {
            "length_mm": round(float(length), 2),
            "width_mm": round(float(width), 2),
            "vertex_count": len(corners),
            "polygon_mm": corners,
            # 1.0 = a perfect rectangle (area of the outline / area of its bounding rectangle)
            "rectangle_fill_ratio": round(float(cv2.contourArea(outer_mm.astype(np.float32)) / (length * width)), 3),
        },
        "hole_count": len(holes),
        "holes": holes,
        "center_on_table_mm": [round(float(cx), 2), round(float(cy), 2)],
    }


def match_holes(measured_holes, truth_holes):
    """Pair each true hole with the nearest measured hole, trying the four axis flips.

    Returns one entry per true hole: its matched measured hole (or None) and the errors.
    """
    truth_centers = np.array([h["center_from_part_center_mm"] for h in truth_holes], dtype=float).reshape(-1, 2)
    best = None
    for flip in FLIPS:
        measured = np.array([h["center_from_part_center_mm"] for h in measured_holes], dtype=float).reshape(-1, 2)
        measured = measured * np.array(flip)
        pairs = [(float(np.linalg.norm(t - m)), i, j) for i, t in enumerate(truth_centers)
                 for j, m in enumerate(measured)]
        used_truth, used_measured, assignment = set(), set(), {}
        for distance, i, j in sorted(pairs):  # greedy: closest pairs first
            if i not in used_truth and j not in used_measured:
                used_truth.add(i)
                used_measured.add(j)
                assignment[i] = (j, distance)
        cost = sum(d for _, d in assignment.values()) + 100 * (len(truth_holes) - len(assignment))
        if best is None or cost < best[0]:
            best = (cost, assignment)
    result = []
    for i, truth_hole in enumerate(truth_holes):
        if i in best[1]:
            j, distance = best[1][i]
            result.append({"truth": truth_hole, "measured": measured_holes[j], "center_error_mm": round(distance, 3),
                           "diameter_error_mm": round(measured_holes[j]["diameter_mm"] - truth_hole["diameter_mm"], 3)})
        else:
            result.append({"truth": truth_hole, "measured": None, "center_error_mm": None, "diameter_error_mm": None})
    return result


def compare_to_truth(table, truth):
    """Errors of a measurement table against a part's ground truth (see parts.template_parts.part_truth)."""
    return {
        "length_mm": round(table["outline"]["length_mm"] - truth["length"], 3),
        "width_mm": round(table["outline"]["width_mm"] - truth["width"], 3),
        "vertex_count": table["outline"]["vertex_count"] - truth["outline_vertices"],
        "hole_count": table["hole_count"] - len(truth["holes"]),
        "holes": [{"true_diameter_mm": m["truth"]["diameter_mm"], "center_error_mm": m["center_error_mm"],
                   "diameter_error_mm": m["diameter_error_mm"]} for m in match_holes(table["holes"], truth["holes"])],
    }


def check_topology(table, truth, center_tolerance_mm=3.0, diameter_tolerance=0.25):
    """Same structure as the truth? Returns (ok, list of reasons it is not)."""
    reasons = []
    if table["outline"]["vertex_count"] != truth["outline_vertices"]:
        reasons.append(f"outline has {table['outline']['vertex_count']} corners, expected {truth['outline_vertices']}")
    if table["hole_count"] != len(truth["holes"]):
        reasons.append(f"{table['hole_count']} holes, expected {len(truth['holes'])}")
    for match in match_holes(table["holes"], truth["holes"]):
        true_d = match["truth"]["diameter_mm"]
        if match["measured"] is None:
            reasons.append(f"no hole matches the {true_d} mm hole")
        elif match["center_error_mm"] > center_tolerance_mm:
            reasons.append(f"{true_d} mm hole is {match['center_error_mm']:.1f} mm off")
        elif abs(match["diameter_error_mm"]) > diameter_tolerance * true_d:
            reasons.append(f"{true_d} mm hole measures {match['measured']['diameter_mm']} mm")
    return not reasons, reasons
