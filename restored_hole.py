"""Deterministic position of a restored (missing or broken-through) hole, no language model.

A completion's x/y pair that matches no measured hole claims a restored hole; its numbers
come from this code, in order: (a) an arc fit to the hole's remaining arc on the outline
(a measurement, shown under Measured), (b) row/column alignment with intact neighbours
(Estimated), (c) the claim kept as the mirror fallback (Estimated). Every answer names its
method: "arc fit", "aligned with neighbours" or "mirrored".
"""
import numpy as np

from break_cues import MIN_ARC_COVERAGE_DEG, _arc_coverage_deg

ARC_SEARCH_MM = 12.0  # outline window around the claimed position searched for the remaining arc:
# the mirror claim can miss by the layout's own asymmetry (6.2 mm seen on BREAK2), plus the radius
ARC_INLIER_MM = 0.5  # radial band (the hole tolerance) for refitting the arc circle


def _points(raw):
    return np.array([[float(v) for v in (p if isinstance(p, list) else p.split())] for p in raw], float)


def _hole_centers(holes):
    """Parsed (x, y) centers; tables store them as pairs or as "u v" strings."""
    centers = []
    for hole in holes:
        center = hole.get("center_from_part_center_mm")
        try:
            x, y = center if isinstance(center, list) else center.split()
            centers.append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    return centers


def median_hole_radius(table):
    """Median radius of the intact (measured) holes, or None when there are none."""
    diameters = [hole["diameter_mm"] for hole in table.get("holes", [])
                 if isinstance(hole.get("diameter_mm"), (int, float))]
    return float(np.median(diameters)) / 2 if diameters else None


def _fit_fixed_radius(points, start, radius, rounds=50):
    """Circle center for a fixed radius by Huber-robust Gauss-Newton from `start`.

    The window also holds straight cut-edge points whose large squared residuals would drag
    a plain fit off the arc; residuals past the inlier band count linearly instead.
    """
    center = np.array(start, float)
    for _ in range(rounds):
        dist = np.linalg.norm(points - center, axis=1)
        dist = np.where(dist < 1e-9, 1e-9, dist)
        residual = dist - radius
        weight = np.minimum(1.0, ARC_INLIER_MM / np.maximum(np.abs(residual), 1e-9))
        step, *_ = np.linalg.lstsq(-(points - center) / dist[:, None] * weight[:, None],
                                   -residual * weight, rcond=None)
        center = center + step
        if float(np.linalg.norm(step)) < 1e-6:
            break
    return center


def fit_arc_center(contour_mm, near_xy, radius_mm):
    """((x, y), coverage_deg) of the remaining hole arc near `near_xy`, fixed `radius_mm`.

    Fits the outline points in the search window (Huber-robust to straight cut-edge points),
    refits the inliers, and keeps the fit only if the inliers cover at least
    MIN_ARC_COVERAGE_DEG (60°) of the circle; else None. Below that the fixed-radius center
    is underconstrained, and a straight cut edge can only cover a short chord anyway.
    """
    points = _points(contour_mm)
    window = points[np.linalg.norm(points - np.array(near_xy, float), axis=1) <= ARC_SEARCH_MM]
    if len(window) < 3:
        return None
    center = _fit_fixed_radius(window, near_xy, radius_mm)
    for _ in range(2):  # refit the inliers, then re-select them around the better center
        window = window[np.abs(np.linalg.norm(window - center, axis=1) - radius_mm) <= ARC_INLIER_MM]
        if len(window) < 3:
            return None
        center = _fit_fixed_radius(window, center, radius_mm)
    coverage = _arc_coverage_deg(window, center, 2 * radius_mm)
    if coverage < MIN_ARC_COVERAGE_DEG:
        return None
    return (float(center[0]), float(center[1])), coverage


def align_to_neighbours(holes, near_xy):
    """(x, y) from the nearest intact column's and row's holes, or None without two distinct mates.

    Rows and columns split where the hole coordinates gap the most; x comes from the hole
    nearest `near_xy` in the nearest column, y from the nearest in the nearest row. One hole
    cannot give both (that would copy it), so a lone neighbour fails to the mirror fallback.
    """
    centers = _hole_centers(holes)
    if not centers:
        return None
    near = (float(near_xy[0]), float(near_xy[1]))

    def groups(axis):
        order = sorted(range(len(centers)), key=lambda i: centers[i][axis])
        if len(order) < 2:
            return [order]
        gaps = [centers[order[k + 1]][axis] - centers[order[k]][axis] for k in range(len(order) - 1)]
        cut = max(range(len(gaps)), key=lambda k: gaps[k])
        return [order[:cut + 1], order[cut + 1:]]

    def pick(axis_groups, axis):
        group = min(axis_groups, key=lambda g: min(abs(centers[i][axis] - near[axis]) for i in g))
        return min(group, key=lambda i: (abs(centers[i][axis] - near[axis]),
                                         abs(centers[i][0] - near[0]) + abs(centers[i][1] - near[1])))

    column_hole, row_hole = pick(groups(0), 0), pick(groups(1), 1)
    if column_hole == row_hole:
        return None
    return centers[column_hole][0], centers[row_hole][1]


def restore_hole_position(table, claimed_xy):
    """((x, y), method) for a restored hole claimed near `claimed_xy`.

    Arc fit first (a measurement), neighbour alignment next, the claim itself last: with no
    arc and no neighbours there is nothing better than the mirror guess, so it is kept and
    labelled "mirrored".
    """
    radius = median_hole_radius(table)
    contour = table.get("outline", {}).get("contour_mm")
    if radius and contour:
        fitted = fit_arc_center(contour, claimed_xy, radius)
        if fitted:
            return fitted[0], "arc fit"
    aligned = align_to_neighbours(table.get("holes", []), claimed_xy)
    if aligned:
        return aligned, "aligned with neighbours"
    return (float(claimed_xy[0]), float(claimed_xy[1])), "mirrored"
