"""Tests for measure.py using synthetic masks with known sizes (no API calls)."""
import cv2
import numpy as np
import pytest

from measure import card_scale, long_side_mm

MM_PER_PIXEL = 0.2


def rotated_rectangle_mask(width_mm, height_mm, angle_deg, mm_per_pixel=MM_PER_PIXEL, canvas=1200):
    """Filled rectangle of the given size in mm, rotated, drawn at mm_per_pixel."""
    rect = ((canvas / 2, canvas / 2), (width_mm / mm_per_pixel, height_mm / mm_per_pixel), angle_deg)
    mask = np.zeros((canvas, canvas), dtype=np.uint8)
    cv2.fillPoly(mask, [cv2.boxPoints(rect).round().astype(np.int32)], 1)
    return mask.astype(bool)


def test_card_scale_recovers_mm_per_pixel():
    scale = card_scale(rotated_rectangle_mask(85.60, 53.98, 17))
    assert scale.mm_per_pixel == pytest.approx(MM_PER_PIXEL, rel=0.01)


def test_part_length_in_mm():
    length, _ = long_side_mm(rotated_rectangle_mask(55.5, 22, -40), MM_PER_PIXEL)
    assert length == pytest.approx(55.5, rel=0.01)
