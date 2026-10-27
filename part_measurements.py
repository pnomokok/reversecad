"""Measurement table of a flat part from its mask: outline size, holes, hole centers (mm).

The mask's outline and holes are mapped to millimeters with a pixel-to-mm
homography. Hole centers are given in the part's own frame: u along the part's
length, v along its width, measured from the part's center. The language model
gets these numbers; it never measures pixels itself.
"""
import math

import cv2
import numpy as np

from homography import to_mm

MIN_HOLE_AREA_MM2 = 0.5  # ignore specks smaller than about 0.8 mm across


def measure_part(part_mask, homography):
    """Return the measurement table as a dict (all lengths in mm)."""
    contours, hierarchy = cv2.findContours(part_mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("part mask is empty")
    parents = hierarchy[0][:, 3]
    outer_index = max((i for i in range(len(contours)) if parents[i] == -1),
                      key=lambda i: cv2.contourArea(contours[i]))
    outer_mm = to_mm(contours[outer_index].reshape(-1, 2), homography).astype(np.float32)

    (cx, cy), (w, h), angle = cv2.minAreaRect(outer_mm)
    length, width = max(w, h), min(w, h)
    axis = math.radians(angle if w >= h else angle + 90)
    cos_a, sin_a = math.cos(axis), math.sin(axis)

    holes = []
    for i in range(len(contours)):
        if parents[i] != outer_index:
            continue
        hole_mm = to_mm(contours[i].reshape(-1, 2), homography).astype(np.float32)
        area = cv2.contourArea(hole_mm)
        if area < MIN_HOLE_AREA_MM2:
            continue
        moments = cv2.moments(hole_mm)
        hx, hy = moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]
        dx, dy = hx - cx, hy - cy
        roundness = None
        if len(hole_mm) >= 5:
            axes = cv2.fitEllipse(hole_mm)[1]
            roundness = min(axes) / max(axes)
        holes.append({
            "center_from_part_center_mm": [round(dx * cos_a + dy * sin_a, 2), round(-dx * sin_a + dy * cos_a, 2)],
            "diameter_mm": round(2 * math.sqrt(area / math.pi), 2),
            "roundness": round(roundness, 3) if roundness is not None else None,
        })
    holes.sort(key=lambda hole: tuple(hole["center_from_part_center_mm"]))

    return {
        "outline": {
            "length_mm": round(length, 2),
            "width_mm": round(width, 2),
            # 1.0 = a perfect rectangle (area of the outline / area of its bounding rectangle)
            "rectangle_fill_ratio": round(cv2.contourArea(outer_mm) / (length * width), 3),
        },
        "hole_count": len(holes),
        "holes": holes,
        "frame": "u along the part's length, v along its width, from the part's center",
        "center_on_table_mm": [round(cx, 2), round(cy, 2)],
    }


def compare_to_truth(table, truth_plate):
    """Errors of a measurement table against the synthetic scene's ground truth."""
    errors = {
        "length_mm": table["outline"]["length_mm"] - truth_plate["length"],
        "width_mm": table["outline"]["width_mm"] - truth_plate["width"],
        "hole_count": table["hole_count"] - truth_plate["hole_count"],
        "hole_diameter_mm": [hole["diameter_mm"] - truth_plate["hole_diameter"] for hole in table["holes"]],
    }
    truth_centers = np.array(truth_plate["hole_centers_from_part_center_mm"])
    measured = np.array([hole["center_from_part_center_mm"] for hole in table["holes"]]).reshape(-1, 2)
    # The part's axis has no "front", so try the four sign flips and keep the best match.
    best = None
    for flip in [(1, 1), (-1, 1), (1, -1), (-1, -1)]:
        flipped = measured * np.array(flip)
        distances = [float(np.min(np.linalg.norm(truth_centers - point, axis=1))) for point in flipped]
        if best is None or sum(distances) < sum(best):
            best = distances
    errors["hole_center_mm"] = best
    return errors
