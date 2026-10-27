"""Refine a part mask's holes from the photo's brightness.

SAM finds the part's outline well but often fills or fragments small holes.
This keeps SAM's outer outline, fills it, and marks as holes the pixels inside
it that look like the background (darker, by an Otsu threshold within the part).
Assumes the part is lighter than the background (e.g. metal on dark fabric).
"""
import cv2
import numpy as np

EDGE_MARGIN_PX = 3  # stay this far inside the outline so edge pixels are not called holes
MIN_HOLE_PX = 30  # ignore dark specks smaller than this


def refine_holes(photo_rgb, part_mask):
    """Return (refined mask, number of holes found)."""
    contours, _ = cv2.findContours(part_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outer = max(contours, key=cv2.contourArea)
    filled = np.zeros(part_mask.shape, dtype=np.uint8)
    cv2.drawContours(filled, [outer], -1, 1, thickness=cv2.FILLED)
    inside = cv2.erode(filled, np.ones((2 * EDGE_MARGIN_PX + 1,) * 2, np.uint8))

    gray = cv2.GaussianBlur(cv2.cvtColor(np.asarray(photo_rgb), cv2.COLOR_RGB2GRAY), (0, 0), 1.0)
    threshold, _ = cv2.threshold(gray[inside > 0].reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = ((gray < threshold) & (inside > 0)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(dark)
    holes = np.zeros_like(dark)
    hole_count = 0
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= MIN_HOLE_PX:
            holes[labels == label] = 1
            hole_count += 1
    # Fill specks inside each hole so a hole is one clean region.
    hole_contours, _ = cv2.findContours(holes, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    holes = np.zeros_like(holes)
    cv2.drawContours(holes, hole_contours, -1, 1, thickness=cv2.FILLED)
    return (filled > 0) & (holes == 0), hole_count
