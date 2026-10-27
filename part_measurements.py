"""Measurement table of a flat part from its mask: outline, corners, holes (mm).

The mask's outline and holes are mapped to millimeters with a pixel-to-mm
homography. Everything is given in the part's own frame [u, v]: u along the
length of the outline's minimum-area rectangle, v along its width, origin at
that rectangle's center. Outline corners come from lines fitted to each edge
and intersected (like the card's corners).

Each hole gets a shape: the best match (by overlap) among an equal-area circle,
a rectangle, a slot (round ends) and an ellipse with the hole's minimum-area-
rectangle size and angle; if none overlaps at least 0.9, it is a polygon given
by its corners.
The language model gets these numbers; it never measures pixels itself.
"""
import math

import cv2
import numpy as np

from homography import to_mm

MIN_HOLE_AREA_MM2 = 0.5  # ignore specks smaller than about 0.8 mm across
POLYGON_EPSILON_MM = 0.8  # max deviation when simplifying an outline to corners
EDGE_TRIM = 0.15  # fraction of each edge ignored at both ends when fitting its line
MAX_CORNER_SHIFT_MM = 3.0  # fall back to the simplified corner if the fitted one moves further
FLIPS = [(1, 1), (-1, 1), (1, -1), (-1, -1)]  # the part's axis has no "front"; mirroring is allowed
SHAPE_MIN_MATCH = 0.9  # overlap needed to call a hole a circle, rectangle or slot
SHAPE_GRID_MM = 0.05  # raster step for comparing a hole with ideal shapes
ROUND_ELONGATION = 1.15  # below this length/width ratio a matching hole is a circle
ELONGATED_SHAPES = ("rectangle", "slot", "ellipse")  # described by length, width and angle


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
    """Corners of a closed outline: simplify, then refine each corner by intersecting fitted edge lines."""
    contour_mm = np.asarray(contour_mm, dtype=np.float64)
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


# ---------- hole shapes ----------
def _rectangle(center, length, width, angle):
    along, across = np.array([math.cos(angle), math.sin(angle)]), np.array([-math.sin(angle), math.cos(angle)])
    return np.array([center + su * length / 2 * along + sv * width / 2 * across
                     for su, sv in [(-1, -1), (1, -1), (1, 1), (-1, 1)]])


def _slot(center, length, width, angle, steps=24):
    """Rectangle with semicircular ends; length is the overall end-to-end length."""
    along, across = np.array([math.cos(angle), math.sin(angle)]), np.array([-math.sin(angle), math.cos(angle)])
    radius, half = width / 2, max(length - width, 0) / 2
    points = []
    for end, start in [(1, -90), (-1, 90)]:
        for a in np.radians(np.linspace(start, start + 180, steps)):
            points.append(center + end * half * along + radius * (math.cos(a) * along + math.sin(a) * across))
    return np.array(points)


def _ellipse(center, length, width, angle, steps=64):
    along, across = np.array([math.cos(angle), math.sin(angle)]), np.array([-math.sin(angle), math.cos(angle)])
    a = np.linspace(0, 2 * math.pi, steps, endpoint=False)
    return center + np.outer(np.cos(a) * length / 2, along) + np.outer(np.sin(a) * width / 2, across)


def _circle(center, diameter, steps=48):
    a = np.linspace(0, 2 * math.pi, steps, endpoint=False)
    return center + diameter / 2 * np.column_stack([np.cos(a), np.sin(a)])


def _overlap(polygon_a, polygon_b):
    """IoU of two polygons (mm), rasterized on a fine grid."""
    both = np.vstack([polygon_a, polygon_b])
    origin = both.min(axis=0) - 1
    size = np.ceil((both.max(axis=0) + 1 - origin) / SHAPE_GRID_MM).astype(int)
    masks = []
    for polygon in (polygon_a, polygon_b):
        mask = np.zeros((size[1], size[0]), dtype=np.uint8)
        pixels = np.round((polygon - origin) / SHAPE_GRID_MM * 16).astype(np.int32)
        cv2.fillPoly(mask, [pixels], 1, shift=4)
        masks.append(mask > 0)
    union = np.count_nonzero(masks[0] | masks[1])
    return np.count_nonzero(masks[0] & masks[1]) / union if union else 0.0


def classify_hole(hole_mm):
    """Return (shape, details) for a hole outline in mm (table frame not applied yet)."""
    area = cv2.contourArea(hole_mm)
    moments = cv2.moments(hole_mm)
    centroid = np.array([moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]])
    (rx, ry), (rw, rh), rangle = cv2.minAreaRect(hole_mm)
    length, width = max(rw, rh), min(rw, rh)
    axis = math.radians(rangle if rw >= rh else rangle + 90)
    center = np.array([rx, ry])
    scores = {
        "circle": _overlap(hole_mm, _circle(centroid, 2 * math.sqrt(area / math.pi))),
        "rectangle": _overlap(hole_mm, _rectangle(center, length, width, axis)),
        "slot": _overlap(hole_mm, _slot(center, length, width, axis)),
        "ellipse": _overlap(hole_mm, _ellipse(center, length, width, axis)),
    }
    if length / width < ROUND_ELONGATION and scores["circle"] >= SHAPE_MIN_MATCH:
        shape = "circle"
    else:
        shape = max(scores, key=scores.get)
        if scores[shape] < SHAPE_MIN_MATCH:
            shape = "polygon"
    return shape, {"centroid": centroid, "rect_center": center, "length": length, "width": width, "axis": axis,
                   "area": area, "match": scores.get(shape, max(scores.values()))}


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
        shape, info = classify_hole(hole_mm)
        roundness = None
        if len(hole_mm) >= 5:
            axes = cv2.fitEllipse(hole_mm)[1]
            roundness = round(float(min(axes) / max(axes)), 3)
        hole = {
            "shape": shape,
            "center_from_part_center_mm": to_part_frame(*info["centroid"]),
            # for a circle its diameter; for other shapes the diameter of a circle with the same area
            "diameter_mm": round(float(2 * math.sqrt(area / math.pi)), 2),
            "roundness": roundness,
            "solidity": round(float(area / cv2.contourArea(cv2.convexHull(hole_mm))), 3),
            "shape_match": round(float(info["match"]), 3),
        }
        if shape in ELONGATED_SHAPES or shape == "polygon":  # a polygon's are its bounding-rectangle size
            relative = math.degrees(info["axis"] - axis) % 180
            relative = relative - 180 if relative > 90 else relative
            hole.update({"center_from_part_center_mm": to_part_frame(*info["rect_center"]),
                         "length_mm": round(float(info["length"]), 2), "width_mm": round(float(info["width"]), 2),
                         "angle_deg": round(relative, 1) if abs(relative) >= 1 else 0.0})
        if shape != "circle":
            hole["polygon_mm"] = [to_part_frame(x, y) for x, y in outline_polygon(hole_mm)]
        holes.append(hole)
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
            measured = measured_holes[j]
            entry = {"truth": truth_hole, "measured": measured, "center_error_mm": round(distance, 3),
                     "diameter_error_mm": round(measured["diameter_mm"] - truth_hole["diameter_mm"], 3)}
            if "length_mm" in truth_hole and "length_mm" in measured:
                entry["length_error_mm"] = round(measured["length_mm"] - truth_hole["length_mm"], 3)
                entry["width_error_mm"] = round(measured["width_mm"] - truth_hole["width_mm"], 3)
            result.append(entry)
        else:
            result.append({"truth": truth_hole, "measured": None, "center_error_mm": None, "diameter_error_mm": None})
    return result


def compare_to_truth(table, truth):
    """Errors of a measurement table against a part's ground truth (see parts.template_parts.part_truth)."""
    holes = []
    for m in match_holes(table["holes"], truth["holes"]):
        entry = {"true_shape": m["truth"].get("shape", "circle"),
                 "measured_shape": m["measured"]["shape"] if m["measured"] else None,
                 "true_diameter_mm": m["truth"]["diameter_mm"], "center_error_mm": m["center_error_mm"],
                 "diameter_error_mm": m["diameter_error_mm"]}
        for key in ("length_error_mm", "width_error_mm"):
            if key in m:
                entry[key] = m[key]
        holes.append(entry)
    return {
        "length_mm": round(table["outline"]["length_mm"] - truth["length"], 3),
        "width_mm": round(table["outline"]["width_mm"] - truth["width"], 3),
        "vertex_count": table["outline"]["vertex_count"] - truth["outline_vertices"],
        "hole_count": table["hole_count"] - len(truth["holes"]),
        "holes": holes,
    }


def check_topology(table, truth, center_tolerance_mm=3.0, size_tolerance=0.25, angle_tolerance_deg=15):
    """Same structure as the truth? Returns (ok, list of reasons it is not)."""
    reasons = []
    if table["outline"]["vertex_count"] != truth["outline_vertices"]:
        reasons.append(f"outline has {table['outline']['vertex_count']} corners, expected {truth['outline_vertices']}")
    if table["hole_count"] != len(truth["holes"]):
        reasons.append(f"{table['hole_count']} holes, expected {len(truth['holes'])}")
    for match in match_holes(table["holes"], truth["holes"]):
        true_hole, measured = match["truth"], match["measured"]
        true_shape = true_hole.get("shape", "circle")
        label = f"{true_hole['diameter_mm']} mm hole" if true_shape == "circle" else \
            f"{true_hole['length_mm']} x {true_hole['width_mm']} {true_shape}"
        if measured is None:
            reasons.append(f"no hole matches the {label}")
        elif match["center_error_mm"] > center_tolerance_mm:
            reasons.append(f"{label} is {match['center_error_mm']:.1f} mm off")
        elif measured["shape"] != true_shape:
            reasons.append(f"{label} measures as a {measured['shape']}")
        elif true_shape == "circle":
            if abs(match["diameter_error_mm"]) > size_tolerance * true_hole["diameter_mm"]:
                reasons.append(f"{label} measures {measured['diameter_mm']} mm")
        else:
            for key in ("length_mm", "width_mm"):
                if abs(measured[key] - true_hole[key]) > size_tolerance * true_hole[key]:
                    reasons.append(f"{label}: {key} {measured[key]}")
            angle_error = abs((measured["angle_deg"] - true_hole["angle_deg"] + 90) % 180 - 90)
            if angle_error > angle_tolerance_deg:
                reasons.append(f"{label} is turned by {angle_error:.0f} degrees")
    return not reasons, reasons
