"""Color-based hole finder: the fallback when SAM's own holes are unreliable.

Keeps SAM's outer outline and fills it. Samples the background color from a
thin ring just outside the outline and the part color from inside it; pixels
inside the outline that are closer to the background color are holes. Works
for parts lighter or darker than the background, as long as the colors differ.
"""
import cv2
import numpy as np

EDGE_MARGIN_PX = 3  # stay this far from the outline on both sides
RING_WIDTH_PX = 15  # width of the background sample ring
MIN_HOLE_PX = 30  # ignore specks smaller than this


def _kernel(radius):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def refine_holes(photo_rgb, part_mask):
    """Return (mask with holes from color, number of holes found)."""
    contours, _ = cv2.findContours(part_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outer = max(contours, key=cv2.contourArea)
    filled = np.zeros(part_mask.shape, dtype=np.uint8)
    cv2.drawContours(filled, [outer], -1, 1, thickness=cv2.FILLED)
    inside = cv2.erode(filled, _kernel(EDGE_MARGIN_PX)) > 0
    ring = (cv2.dilate(filled, _kernel(EDGE_MARGIN_PX + RING_WIDTH_PX)) > 0) & \
           ~(cv2.dilate(filled, _kernel(EDGE_MARGIN_PX)) > 0)

    color = cv2.GaussianBlur(np.asarray(photo_rgb).astype(np.float32), (0, 0), 1.0)
    background = np.median(color[ring], axis=0)
    part = np.median(color[inside], axis=0)  # holes are a small share, so the median is the part
    closer_to_background = np.linalg.norm(color - background, axis=2) < np.linalg.norm(color - part, axis=2)
    candidates = (closer_to_background & inside).astype(np.uint8)
    candidates = cv2.morphologyEx(candidates, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates)
    holes = np.zeros_like(candidates)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= MIN_HOLE_PX:
            holes[labels == label] = 1
    # Fill specks inside each hole so a hole is one clean region.
    hole_contours, _ = cv2.findContours(holes, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    holes = np.zeros_like(holes)
    cv2.drawContours(holes, hole_contours, -1, 1, thickness=cv2.FILLED)
    return (filled > 0) & (holes == 0), len(hole_contours)
