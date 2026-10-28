"""Cues that a measured part may be broken or incomplete, computed from its measurement table.

Code finds the evidence; Muse Wonder (completion step) only interprets it. All positions are in the
table's frame: mm from the part's bounding-rectangle center, u along its length, v across.

  rough_edge:        an outline edge whose points fit neither a straight line nor an arc (a break
                     zigzags; designed edges are straight or round).
  missing_material:  the part is nearly symmetric about u = 0 or v = 0, and a region of its mirror image
                     is missing from it next to a rough edge (a broken-off corner or end).
  missing_hole:      equal holes form a mirror pattern with a gap where there is material (not drilled).
  partial_hole:      the pattern expects a hole where the outline follows part of its circle (broken through a hole).
"""
import math

import cv2
import numpy as np

from model_view import fit_circle, resample

ROUGH_RMS_MM = 0.15  # an edge whose points stray more than this from a line and from a circle is rough
EDGE_MARGIN_MM = 1.5  # points this close to an edge's ends belong to the corner, not the edge
MIN_ROUGH_EDGE_MM = 3.0
SYMMETRY_MIN_IOU = 0.9  # below this the part is not meant to be symmetric about that axis
MIN_MISSING_AREA_MM2 = 5.0
RASTER_MM = 0.25
PATTERN_MATCH_MM = 1.0  # a mirrored hole this close to another hole of the group supports the pattern
HOLE_PRESENT_MM = 1.5  # a hole this close to an expected position fills it
ARC_TOLERANCE_MM = 0.35  # outline points this close to an expected hole's circle lie on it
MIN_ARC_COVERAGE_DEG = 60  # the outline must follow at least this much of that circle to be a partial hole


def _point_segment(points, a, b):
    """(distance of each point to segment a-b, position along it in mm)."""
    direction = b - a
    length = np.linalg.norm(direction)
    t = np.clip((points - a) @ direction / length, 0, length)
    return np.linalg.norm(points - (a + np.outer(t / length, direction)), axis=1), t


def rough_edges(table):
    """Edges of the simplified outline whose contour points are rough (see module docstring)."""
    contour = resample(np.array(table["outline"]["contour_mm"], float))
    corners = np.array(table["outline"]["simplified_polygon_mm"], float)
    edges = list(zip(corners, np.roll(corners, -1, axis=0)))
    distances = np.array([_point_segment(contour, a, b)[0] for a, b in edges])
    nearest = distances.argmin(axis=0)
    found = []
    for i, (a, b) in enumerate(edges):
        length = float(np.linalg.norm(b - a))
        distance, along = _point_segment(contour, a, b)
        keep = (nearest == i) & (along > EDGE_MARGIN_MM) & (along < length - EDGE_MARGIN_MM)
        points = contour[keep]
        if length < MIN_ROUGH_EDGE_MM or len(points) < 10:
            continue
        line_rms = float(np.sqrt(np.mean(distance[keep] ** 2)))
        circle_rms = fit_circle(points)[2]
        if min(line_rms, circle_rms) > ROUGH_RMS_MM:
            found.append({"kind": "rough_edge", "from": [round(float(v), 2) for v in a],
                          "to": [round(float(v), 2) for v in b], "length_mm": round(length, 2),
                          "roughness_mm": round(min(line_rms, circle_rms), 3), "_points": points})
    return found


def _raster(table):
    """The outline filled on a square grid centered on the frame's origin: (mask, mm per pixel, half size)."""
    contour = np.array(table["outline"]["contour_mm"], float)
    half = float(np.abs(contour).max()) + 2.0
    size = int(math.ceil(2 * half / RASTER_MM)) | 1  # odd, so the origin is a pixel center
    pixels = np.round((contour + half) / RASTER_MM).astype(np.int32)
    mask = np.zeros((size, size), np.uint8)
    cv2.fillPoly(mask, [pixels], 1)
    return mask.astype(bool), half


def missing_material(table, rough):
    """Regions of the mirror image (about u = 0 or v = 0) missing from a nearly symmetric part, next to a rough edge."""
    mask, half = _raster(table)
    rough_points = np.vstack([edge["_points"] for edge in rough]) if rough else np.zeros((0, 2))
    found = []
    for axis, mirror in (("u = 0", np.fliplr(mask)), ("v = 0", np.flipud(mask))):
        union = np.count_nonzero(mask | mirror)
        symmetry = np.count_nonzero(mask & mirror) / union if union else 0.0
        if symmetry < SYMMETRY_MIN_IOU:
            continue
        missing = cv2.morphologyEx((mirror & ~mask).astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(missing)
        for label in range(1, count):
            area = stats[label, cv2.CC_STAT_AREA] * RASTER_MM**2
            if area < MIN_MISSING_AREA_MM2:
                continue
            ys, xs = np.nonzero(labels == label)
            box = [xs.min() * RASTER_MM - half, ys.min() * RASTER_MM - half,
                   (xs.max() + 1) * RASTER_MM - half, (ys.max() + 1) * RASTER_MM - half]
            near_rough = len(rough_points) and np.any(
                (rough_points[:, 0] > box[0] - 1.5) & (rough_points[:, 0] < box[2] + 1.5)
                & (rough_points[:, 1] > box[1] - 1.5) & (rough_points[:, 1] < box[3] + 1.5))
            if not near_rough:
                continue  # an asymmetric design feature, not a break
            if any(_overlap(box, cue["bbox_mm"]) for cue in found):
                continue  # the same region seen from the other axis
            found.append({"kind": "missing_material", "mirror_axis": axis, "symmetry_iou": round(symmetry, 3),
                          "area_mm2": round(float(area), 1), "bbox_mm": [round(float(v), 2) for v in box]})
    return found


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _hole_groups(holes):
    groups = []
    for hole in holes:
        group = next((g for g in groups if g[0]["shape"] == hole["shape"]
                      and abs(g[0]["diameter_mm"] - hole["diameter_mm"]) <= max(0.3, 0.05 * hole["diameter_mm"])), None)
        if group:
            group.append(hole)
        else:
            groups.append([hole])
    return groups


def _material_fraction(contour, center, diameter):
    """Share of a hole-sized disk at `center` that lies inside the outline."""
    angles = np.linspace(0, 2 * np.pi, 16, endpoint=False)
    samples = [center] + [center + r * np.array([math.cos(a), math.sin(a)])
                          for r in (diameter / 4, diameter / 2) for a in angles]
    inside = [cv2.pointPolygonTest(contour, (float(x), float(y)), False) >= 0 for x, y in samples]
    return sum(inside) / len(inside)


def _arc_coverage_deg(points, center, diameter):
    """How much of the hole's circle (in degrees, 10-degree bins) the outline follows."""
    distance = np.linalg.norm(points - center, axis=1)
    on_circle = points[np.abs(distance - diameter / 2) < ARC_TOLERANCE_MM]
    if not len(on_circle):
        return 0
    angles = np.degrees(np.arctan2(on_circle[:, 1] - center[1], on_circle[:, 0] - center[0])) % 360
    return 10 * len(set((angles // 10).astype(int)))


def pattern_gaps(table):
    """Positions where a mirror pattern of equal holes expects a hole that is missing or cut by the outline.

    missing_hole: material all around the place (never drilled). partial_hole: the outline follows part
    of the hole's circle (the part broke through the hole, half of it is left as a notch).
    """
    contour = np.array(table["outline"]["contour_mm"], np.float32)
    outline_points = resample(contour.astype(float))
    found = []
    for group in _hole_groups(table["holes"]):
        centers = np.array([h["center_from_part_center_mm"] for h in group], float)
        diameter = float(np.mean([h["diameter_mm"] for h in group]))
        for flip in (np.array([-1, 1]), np.array([1, -1]), np.array([-1, -1])):
            mirrored = centers * flip
            # The pattern exists for this mirror if it maps some hole onto another existing hole.
            if len(centers) < 2 or not any(np.linalg.norm(centers - m, axis=1).min() < PATTERN_MATCH_MM
                                           for i, m in enumerate(mirrored)
                                           if np.linalg.norm(m - centers[i]) > PATTERN_MATCH_MM):
                continue
            for source, expected in zip(centers, mirrored):
                if np.linalg.norm(centers - expected, axis=1).min() < HOLE_PRESENT_MM:
                    continue
                if any(np.linalg.norm(np.array(cue["expected_at_mm"]) - expected) < HOLE_PRESENT_MM for cue in found):
                    continue
                fraction = _material_fraction(contour, expected, diameter)
                coverage = _arc_coverage_deg(outline_points, expected, diameter)
                if fraction > 0.9:
                    kind = "missing_hole"
                elif coverage >= MIN_ARC_COVERAGE_DEG:
                    kind = "partial_hole"
                else:
                    continue  # the place itself is gone; missing_material covers it
                found.append({"kind": kind, "expected_at_mm": [round(float(v), 2) for v in expected],
                              "diameter_mm": round(diameter, 2), "material_fraction": round(fraction, 2),
                              "outline_follows_circle_deg": coverage,
                              "mirror_of_mm": [round(float(v), 2) for v in source], "shape": group[0]["shape"]})
    return found


def find_break_cues(table):
    """All cues for one measured part: {"break_likely": bool, "cues": [...]}, positions in the table's frame.

    Tables from before the detailed outline was measured (no contour_mm) give {"break_likely": None}.
    """
    if "contour_mm" not in table["outline"]:
        return {"break_likely": None, "cues": [], "note": "no detailed outline in this measurement table"}
    rough = rough_edges(table)
    cues = rough + missing_material(table, rough) + pattern_gaps(table)
    return {"break_likely": bool(cues), "cues": [{k: v for k, v in cue.items() if not k.startswith("_")} for cue in cues]}
