"""Surface appearances for synthetic scenes: plain painted approximations, no physical realism.

Each painter fills the part's canvas mask with a flat base color plus a simple
texture. They exist to test whether the frozen pipeline copes with parts that do
not look like a flat light plate — not to imitate real materials. Painters use
their own derived random stream, so the scene's background, tilt, blur and noise
stay identical across appearances (only the part surface differs).
"""
import cv2
import numpy as np

APPEARANCES = ("brushed", "black_plastic", "wood", "glossy_white")


def _base(height, width, color):
    """Flat base color as float RGB."""
    return np.dstack([np.full((height, width), color[i], dtype=np.float32) for i in range(3)])


def _brushed(height, width, part_mask, rng):
    """Light grey with directional streaks and one soft specular band (fake highlight)."""
    surface = _base(height, width, (172, 175, 180))
    streaks = cv2.blur(rng.normal(0, 6, (height, width)).astype(np.float32), (41, 1))
    surface += streaks[..., None]
    rows, cols = np.nonzero(part_mask)
    u = (cols - cols.min()) / max(cols.max() - cols.min(), 1)  # 0..1 across the part
    v = (rows - rows.min()) / max(rows.max() - rows.min(), 1)
    band = 45 * np.exp(-(((u - 0.35) * 0.8 + (v - 0.5) * 0.6) / 0.12) ** 2)
    surface[rows, cols] += band[:, None]
    return surface


def _black_plastic(height, width, part_mask, rng):
    """Very dark part with faint mottling: low contrast against the dark background."""
    surface = _base(height, width, (22, 22, 26))
    mottle = cv2.blur(rng.normal(0, 2.0, (height, width)).astype(np.float32), (121, 121))
    surface += mottle[..., None]
    return surface


def _wood(height, width, part_mask, rng):
    """Warm base with darker wavy grain lines running along x (fake grain)."""
    surface = _base(height, width, (172, 128, 88))
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    grain = (14 * np.sin(2 * np.pi * (xs * 0.006 + 0.8 * np.sin(ys * 0.01)))
             + 6 * np.sin(2 * np.pi * xs * 0.023 + 1.0))
    grain += rng.normal(0, 2.0, (height, width))
    surface -= grain[..., None]
    return surface


def _hole_blobs(part_mask):
    """(centroid, radius) of each hole, from background blobs inside the filled outline."""
    filled = np.zeros_like(part_mask)
    contours, _ = cv2.findContours(part_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    holes_only = ((filled > 0) & (part_mask == 0)).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(holes_only)
    blobs = []
    for i in range(1, count):
        area = stats[i, cv2.CC_STAT_AREA]
        if area > 50:
            blobs.append((centroids[i], (area / np.pi) ** 0.5))
    return blobs


def _glossy_white(height, width, part_mask, rng):
    """Bright white with one soft highlight blob beside each hole (fake gloss)."""
    del rng  # deterministic from the hole layout
    surface = _base(height, width, (233, 233, 236))
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float32)
    for (cx, cy), radius in _hole_blobs(part_mask):
        spot_x, spot_y = cx - 0.7 * radius, cy - 0.7 * radius  # upper-left light
        sigma = max(0.9 * radius, 1.0)
        surface += (28 * np.exp(-((xs - spot_x) ** 2 + (ys - spot_y) ** 2) / (2 * sigma ** 2)))[..., None]
    return surface


PAINTERS = {"brushed": _brushed, "black_plastic": _black_plastic, "wood": _wood,
            "glossy_white": _glossy_white}


def paint_surface(height, width, part_mask, appearance, seed):
    """Part surface for `appearance` as float RGB (caller clips and composites it)."""
    rng = np.random.default_rng((seed, APPEARANCES.index(appearance)))
    return PAINTERS[appearance](height, width, part_mask, rng)
