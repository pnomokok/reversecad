"""Silhouette IoU after canonical alignment (translation + rotation only, never scale).

Both masks are brought to one mm-per-pixel scale using their *known* scales,
then each is moved to its centroid and rotated so its principal axis is
horizontal. Scale is never fitted: a part that is 10% too large must score
lower, otherwise dimension errors would be hidden.

The principal axis has no "front": the shape may be rotated 180 degrees or
mirrored (part flipped over when photographed). So the candidate is tried in
four variants (0/180 degrees x mirrored or not) and the best IoU wins.
"""
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# Variant name -> (rotation in degrees, mirrored)
VARIANTS = {
    "rot0": (0, False),
    "rot180": (180, False),
    "mirror": (0, True),
    "mirror_rot180": (180, True),
}


@dataclass
class AlignmentResult:
    iou: float
    rotation_deg: int  # 0 or 180, applied to the candidate after axis alignment
    mirrored: bool  # candidate was mirrored left-right after axis alignment
    variant_ious: dict = field(default_factory=dict)  # IoU of every variant tried
    reference: np.ndarray = None  # aligned reference mask (bool)
    candidate: np.ndarray = None  # aligned candidate mask in the winning variant (bool)


def _centroid_and_angle(mask):
    """Centroid (x, y) in pixels and principal-axis angle in radians (image coords)."""
    moments = cv2.moments((mask > 0).astype(np.uint8), binaryImage=True)
    if moments["m00"] == 0:
        raise ValueError("mask is empty")
    cx = moments["m10"] / moments["m00"]
    cy = moments["m01"] / moments["m00"]
    angle = 0.5 * math.atan2(2 * moments["mu11"], moments["mu20"] - moments["mu02"])
    return cx, cy, angle


def _canonicalize(mask, scale, canvas_size):
    """Resample the mask by `scale`, centroid to canvas center, principal axis horizontal."""
    cx, cy, angle = _centroid_and_angle(mask)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    # Rotate by -angle and scale, around the centroid.
    linear = scale * np.array([[cos_a, sin_a], [-sin_a, cos_a]])
    center = (canvas_size - 1) / 2
    offset = np.array([center, center]) - linear @ np.array([cx, cy])
    matrix = np.hstack([linear, offset[:, None]])
    warped = cv2.warpAffine(
        (mask > 0).astype(np.float32), matrix, (canvas_size, canvas_size), flags=cv2.INTER_LINEAR
    )
    return warped >= 0.5


def _iou(a, b):
    union = np.count_nonzero(a | b)
    return np.count_nonzero(a & b) / union if union else 0.0


def aligned_iou(reference_mask, reference_mm_per_pixel, candidate_mask, candidate_mm_per_pixel):
    """IoU between two silhouettes after scale normalization and canonical alignment.

    reference_mask is typically the SAM mask (scale from the card), candidate_mask
    the rendered CadQuery silhouette (scale from the renderer).
    """
    # Compare at the coarser scale so neither mask is upsampled past its detail.
    working_mm_per_pixel = max(reference_mm_per_pixel, candidate_mm_per_pixel)
    reference_scale = reference_mm_per_pixel / working_mm_per_pixel
    candidate_scale = candidate_mm_per_pixel / working_mm_per_pixel

    # Square canvas large enough for either mask at any rotation.
    diagonals = [
        math.hypot(*reference_mask.shape) * reference_scale,
        math.hypot(*candidate_mask.shape) * candidate_scale,
    ]
    canvas_size = math.ceil(max(diagonals)) + 4

    reference = _canonicalize(reference_mask, reference_scale, canvas_size)
    candidate = _canonicalize(candidate_mask, candidate_scale, canvas_size)

    # Rotating 180 degrees / mirroring about the canvas center keeps the centroid in place.
    best = None
    variant_ious = {}
    for name, (rotation_deg, mirrored) in VARIANTS.items():
        variant = np.fliplr(candidate) if mirrored else candidate
        if rotation_deg == 180:
            variant = np.rot90(variant, 2)
        score = _iou(reference, variant)
        variant_ious[name] = score
        if best is None or score > best.iou:
            best = AlignmentResult(score, rotation_deg, mirrored, reference=reference, candidate=variant)
    best.variant_ious = variant_ious
    return best
