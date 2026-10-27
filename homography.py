"""Perspective correction from the card's four corners.

Corners: the card has rounded corners, so they are not read from the mask
directly. A line is fitted to the straight middle part of each side (both
ends trimmed) and corners are where neighboring lines intersect.

Tilt check: in a straight-down shot opposite card edges have equal length.
If left vs right or top vs bottom differ by more than 2%, the camera is tilted.

The homography maps photo pixels to millimeters on the table plane, so part
outlines can be measured in mm directly.
"""
import math

import cv2
import numpy as np

from measure import CARD_LONG_MM, CARD_SHORT_MM

MAX_EDGE_DIFFERENCE = 0.02
SIDE_TRIM = 0.15  # fraction ignored at both ends of each side (rounded corners)
SIDE_TOLERANCE = 0.05  # max distance from a rough side, as a fraction of its length


def largest_contour(mask):
    """Outline of the largest blob as an (N, 2) float array of pixel coordinates."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("mask is empty")
    return max(contours, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)


def _order_corners(points):
    """Order four points as top-left, top-right, bottom-right, bottom-left."""
    center = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - center[1], points[:, 0] - center[0])
    ordered = points[np.argsort(angles)]  # clockwise on screen, since y grows downward
    start = np.argmin(ordered.sum(axis=1))
    return np.roll(ordered, -start, axis=0)


def _fit_side(contour, start, end):
    """Fit a line (point, direction) to contour points on the middle of one side."""
    length = np.linalg.norm(end - start)
    along = (end - start) / length
    normal = np.array([-along[1], along[0]])
    relative = contour - start
    position = relative @ along / length
    distance = np.abs(relative @ normal)
    keep = (position > SIDE_TRIM) & (position < 1 - SIDE_TRIM) & (distance < SIDE_TOLERANCE * length)
    if keep.sum() < 2:
        raise ValueError("not enough points on a card side")
    vx, vy, x0, y0 = cv2.fitLine(contour[keep].astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    return np.array([x0, y0]), np.array([vx, vy])


def _intersect(line_a, line_b):
    (point_a, dir_a), (point_b, dir_b) = line_a, line_b
    # point_a + s * dir_a = point_b + t * dir_b
    s, _ = np.linalg.solve(np.column_stack([dir_a, -dir_b]), point_b - point_a)
    return point_a + s * dir_a


def card_corners(contour):
    """Card corners (top-left, top-right, bottom-right, bottom-left) from its outline."""
    hull = cv2.convexHull(contour.astype(np.float32))
    perimeter = cv2.arcLength(hull, True)
    rough = None
    for epsilon in np.linspace(0.005, 0.1, 60):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            rough = _order_corners(approx.reshape(4, 2).astype(np.float64))
            break
    if rough is None:
        raise ValueError("could not find four card sides")
    # Side i runs from rough corner i to i+1: top, right, bottom, left.
    sides = [_fit_side(contour, rough[i], rough[(i + 1) % 4]) for i in range(4)]
    # Corner i is where side i-1 meets side i.
    return np.array([_intersect(sides[i - 1], sides[i]) for i in range(4)])


def edge_differences(corners):
    """Relative length difference of opposite edges: (left vs right, top vs bottom)."""
    top_left, top_right, bottom_right, bottom_left = corners
    top = np.linalg.norm(top_right - top_left)
    bottom = np.linalg.norm(bottom_right - bottom_left)
    left = np.linalg.norm(bottom_left - top_left)
    right = np.linalg.norm(bottom_right - top_right)
    return (left - right) / ((left + right) / 2), (top - bottom) / ((top + bottom) / 2)


def is_tilted(differences):
    return max(abs(d) for d in differences) > MAX_EDGE_DIFFERENCE


def card_homography(corners):
    """Homography from photo pixels to mm, plus the card size (width, height) in mm.

    The card keeps its orientation: if its long edges run left-right in the
    photo, the mm frame is 85.60 wide; otherwise 53.98 wide.
    """
    top_left, top_right, bottom_right, bottom_left = corners
    horizontal = np.linalg.norm(top_right - top_left) + np.linalg.norm(bottom_right - bottom_left)
    vertical = np.linalg.norm(bottom_left - top_left) + np.linalg.norm(bottom_right - top_right)
    width, height = (CARD_LONG_MM, CARD_SHORT_MM) if horizontal > vertical else (CARD_SHORT_MM, CARD_LONG_MM)
    target = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
    return cv2.getPerspectiveTransform(corners.astype(np.float32), target), (width, height)


def to_mm(points, homography):
    """Map (N, 2) pixel coordinates to (N, 2) mm coordinates on the table plane."""
    mapped = cv2.perspectiveTransform(points.reshape(-1, 1, 2).astype(np.float64), homography)
    return mapped.reshape(-1, 2)


def long_side_mm(contour_mm):
    """Long side of the minimum-area rectangle around an outline given in mm."""
    rect = cv2.minAreaRect(contour_mm.astype(np.float32))
    return max(rect[1]), rect


def rectify_image(image_rgb, homography, region_mm, mm_per_pixel=0.1):
    """Top-down view of region_mm = (x_min, y_min, x_max, y_max) on the table, in mm."""
    x_min, y_min, x_max, y_max = region_mm
    to_pixels = np.array([
        [1 / mm_per_pixel, 0, -x_min / mm_per_pixel],
        [0, 1 / mm_per_pixel, -y_min / mm_per_pixel],
        [0, 0, 1],
    ])
    size = (math.ceil((x_max - x_min) / mm_per_pixel), math.ceil((y_max - y_min) / mm_per_pixel))
    return cv2.warpPerspective(np.asarray(image_rgb), to_pixels @ homography, size), to_pixels
