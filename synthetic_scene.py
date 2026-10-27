"""Synthetic top-down photo for the end-to-end test: the holed plate next to an ID-1 card.

The scene is laid out on the table in millimeters (x right, y down), drawn on a
fine canvas, then projected into a 2048 x 1536 photo with a slight perspective
tilt, blur and noise. The plate silhouette comes from the CadQuery part itself.
Returns the photo, ground-truth masks in photo pixels, and the true dimensions.
"""
import math

import cv2
import numpy as np

from measure import CARD_LONG_MM, CARD_SHORT_MM
from parts.holed_plate import make_holed_plate
from render_silhouette import render_top_silhouette

CANVAS_MM_PER_PIXEL = 0.05
WORLD_MM = (-20.0, -60.0, 215.0, 115.0)  # x_min, y_min, x_max, y_max of the drawn table area
PHOTO_SIZE = (2048, 1536)
CARD_CORNER_RADIUS_MM = 3.18  # ID-1 corner radius
PLATE = {"length": 80.0, "width": 40.0, "thickness": 3.0, "hole_diameter": 6.0, "hole_inset": 8.0}
PLATE_CENTER_MM = (145.0, 27.0)
PLATE_ANGLE_DEG = 8.0
# Field of view on the table and how its corners land in the photo. Squeezing the
# top edge by TILT_PX on each side imitates a camera tilted slightly toward the bottom.
FIELD_CENTER_MM = (95.0, 27.5)
FIELD_SIZE_MM = (220.0, 165.0)
TILT_PX = 40
NOISE_SIGMA = 4.0


def _canvas_from_world():
    """Matrix mapping table mm to canvas pixels."""
    x_min, y_min = WORLD_MM[0], WORLD_MM[1]
    scale = 1 / CANVAS_MM_PER_PIXEL
    return np.array([[scale, 0, -x_min * scale], [0, scale, -y_min * scale], [0, 0, 1]])


def _to_canvas(points_mm):
    points = np.asarray(points_mm, dtype=np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(points, _canvas_from_world()).reshape(-1, 2)


def _rounded_rectangle_mm(x0, y0, width, height, radius, steps=16):
    """Outline of a rounded rectangle, clockwise on screen (y down)."""
    points = []
    for cx, cy, start in [
        (x0 + width - radius, y0 + radius, -90),
        (x0 + width - radius, y0 + height - radius, 0),
        (x0 + radius, y0 + height - radius, 90),
        (x0 + radius, y0 + radius, 180),
    ]:
        for angle in np.radians(np.linspace(start, start + 90, steps)):
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return np.array(points)


def _fill(canvas, points_mm, color):
    """Fill a polygon given in mm with sub-pixel precision."""
    pixels = np.round(_to_canvas(points_mm) * 16).astype(np.int32)
    cv2.fillPoly(canvas, [pixels], color, lineType=cv2.LINE_AA, shift=4)


def _background(height, width, rng):
    """Dark blue fabric: base color plus soft blotches."""
    blotches = cv2.resize(rng.normal(0, 1, (height // 64 + 1, width // 64 + 1)), (width, height),
                          interpolation=cv2.INTER_CUBIC)
    base = np.array([38, 44, 68], dtype=np.float32)
    return np.clip(base + blotches[..., None] * 6, 0, 255)


def _card_mask_and_art(shape):
    """Card mask on the canvas plus the card's printed artwork (RGB)."""
    mask = np.zeros(shape[:2], dtype=np.uint8)
    _fill(mask, _rounded_rectangle_mm(0, 0, CARD_LONG_MM, CARD_SHORT_MM, CARD_CORNER_RADIUS_MM), 255)
    art = np.zeros(shape, dtype=np.uint8)
    art[:] = (236, 232, 220)  # cream card body
    _fill(art, [(0, 0), (CARD_LONG_MM, 0), (CARD_LONG_MM, 13), (0, 13)], (40, 90, 160))  # blue band
    _fill(art, [(9, 20), (21, 20), (21, 29), (9, 29)], (205, 175, 95))  # chip
    origin = _to_canvas([(52, 10)])[0].astype(int)
    cv2.putText(art, "BANK", tuple(origin), cv2.FONT_HERSHEY_SIMPLEX, 3.2, (245, 245, 245), 8, cv2.LINE_AA)
    origin = _to_canvas([(9, 42)])[0].astype(int)
    cv2.putText(art, "0000 0000 0000 0000", tuple(origin), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (70, 70, 80), 5,
                cv2.LINE_AA)
    return mask, art


def _plate_mask(shape):
    """CadQuery plate silhouette, rotated and placed on the canvas."""
    silhouette = render_top_silhouette(make_holed_plate(**PLATE), CANVAS_MM_PER_PIXEL, margin_mm=2.0)
    source_center = ((silhouette.shape[1] - 1) / 2, (silhouette.shape[0] - 1) / 2)
    matrix = cv2.getRotationMatrix2D(source_center, PLATE_ANGLE_DEG, 1.0)
    target_center = _to_canvas([PLATE_CENTER_MM])[0]
    matrix[:, 2] += target_center - np.array(source_center)
    placed = cv2.warpAffine(silhouette.astype(np.float32) / 255, matrix, (shape[1], shape[0]))
    return (placed >= 0.5).astype(np.uint8) * 255


def photo_from_world():
    """Homography mapping table mm to photo pixels (the 'camera')."""
    cx, cy = FIELD_CENTER_MM
    half_w, half_h = FIELD_SIZE_MM[0] / 2, FIELD_SIZE_MM[1] / 2
    world = np.float32([[cx - half_w, cy - half_h], [cx + half_w, cy - half_h],
                        [cx + half_w, cy + half_h], [cx - half_w, cy + half_h]])
    w, h = PHOTO_SIZE
    photo = np.float32([[TILT_PX, 0], [w - 1 - TILT_PX, 0], [w - 1, h - 1], [0, h - 1]])
    return cv2.getPerspectiveTransform(world, photo)


def make_scene(seed=0):
    """Return (photo_rgb, {"card": mask, "plate": mask}, truth dict)."""
    rng = np.random.default_rng(seed)
    width = round((WORLD_MM[2] - WORLD_MM[0]) / CANVAS_MM_PER_PIXEL)
    height = round((WORLD_MM[3] - WORLD_MM[1]) / CANVAS_MM_PER_PIXEL)

    canvas = _background(height, width, rng)
    card_mask, card_art = _card_mask_and_art((height, width, 3))
    plate_mask = _plate_mask((height, width))
    canvas = np.where(card_mask[..., None] > 0, card_art.astype(np.float32) * (card_mask[..., None] / 255)
                      + canvas * (1 - card_mask[..., None] / 255), canvas)
    brushed = cv2.blur(rng.normal(0, 6, (height, width)).astype(np.float32), (41, 1))  # brushed metal streaks
    metal = np.dstack([172 + brushed, 175 + brushed, 180 + brushed])
    canvas = np.where(plate_mask[..., None] > 0, metal, canvas)
    canvas = cv2.GaussianBlur(canvas.astype(np.float32), (0, 0), 1.0)  # avoid aliasing when shrinking

    to_photo = photo_from_world() @ np.linalg.inv(_canvas_from_world())
    photo = cv2.warpPerspective(canvas, to_photo, PHOTO_SIZE, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    photo = cv2.GaussianBlur(photo, (0, 0), 0.8) + rng.normal(0, NOISE_SIGMA, photo.shape)
    photo = np.clip(photo, 0, 255).astype(np.uint8)

    masks = {
        name: cv2.warpPerspective(mask, to_photo, PHOTO_SIZE, flags=cv2.INTER_LINEAR) >= 128
        for name, mask in [("card", card_mask), ("plate", plate_mask)]
    }
    inset = PLATE["hole_inset"]
    half_u, half_v = PLATE["length"] / 2 - inset, PLATE["width"] / 2 - inset
    truth = {
        "plate": {
            **PLATE,
            "hole_count": 4,
            "hole_centers_from_part_center_mm": [[su * half_u, sv * half_v] for su in (-1, 1) for sv in (-1, 1)],
            "center_on_table_mm": list(PLATE_CENTER_MM),
            "angle_deg": PLATE_ANGLE_DEG,
        },
        "card_mm": [CARD_LONG_MM, CARD_SHORT_MM],
        "photo_from_world": photo_from_world().tolist(),
    }
    return photo, masks, truth
