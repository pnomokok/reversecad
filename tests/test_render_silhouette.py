"""Tests for render_silhouette: measurements taken from the rendered mask
must match the plate's known millimeter dimensions."""
import math

import cv2
import numpy as np
import pytest

from parts.holed_plate import make_holed_plate
from render_silhouette import render_top_silhouette

MM_PER_PIXEL = 0.1


def expected_area(length, width, hole_diameter, hole_count=4):
    return length * width - hole_count * math.pi * (hole_diameter / 2) ** 2


def outer_and_hole_contours(mask):
    """Split contours into outer boundaries and holes (top-level vs nested)."""
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    outers = [c for c, h in zip(contours, hierarchy[0]) if h[3] == -1]
    holes = [c for c, h in zip(contours, hierarchy[0]) if h[3] != -1]
    return outers, holes


def test_area_matches_geometry():
    mask = render_top_silhouette(make_holed_plate(), MM_PER_PIXEL)
    area_mm2 = np.count_nonzero(mask) * MM_PER_PIXEL**2
    assert area_mm2 == pytest.approx(expected_area(80, 40, 6), rel=0.01)


def test_outer_size_matches_length_and_width():
    mask = render_top_silhouette(make_holed_plate(), MM_PER_PIXEL)
    ys, xs = np.nonzero(mask)
    width_mm = (xs.max() - xs.min() + 1) * MM_PER_PIXEL
    height_mm = (ys.max() - ys.min() + 1) * MM_PER_PIXEL
    assert width_mm == pytest.approx(80, abs=2 * MM_PER_PIXEL)
    assert height_mm == pytest.approx(40, abs=2 * MM_PER_PIXEL)


def test_finds_one_outline_and_four_holes():
    mask = render_top_silhouette(make_holed_plate(), MM_PER_PIXEL)
    outers, holes = outer_and_hole_contours(mask)
    assert len(outers) == 1
    assert len(holes) == 4


def test_hole_diameter_and_position():
    mask = render_top_silhouette(make_holed_plate(hole_diameter=6, hole_inset=8), MM_PER_PIXEL)
    _, holes = outer_and_hole_contours(mask)
    for hole in holes:
        # Equivalent diameter from the hole's enclosed area.
        diameter_mm = 2 * math.sqrt(cv2.contourArea(hole) / math.pi) * MM_PER_PIXEL
        assert diameter_mm == pytest.approx(6, abs=0.2)

    # Hole centers sit 8 mm in from the plate edges: 32 mm and 12 mm from the center.
    ys, xs = np.nonzero(mask)
    center_x, center_y = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    for hole in holes:
        (hx, hy), _ = cv2.minEnclosingCircle(hole)
        assert abs(hx - center_x) * MM_PER_PIXEL == pytest.approx(32, abs=0.2)
        assert abs(hy - center_y) * MM_PER_PIXEL == pytest.approx(12, abs=0.2)


def test_changing_a_parameter_changes_the_silhouette():
    small = render_top_silhouette(make_holed_plate(hole_diameter=6), MM_PER_PIXEL)
    large = render_top_silhouette(make_holed_plate(hole_diameter=10), MM_PER_PIXEL)
    removed_mm2 = (np.count_nonzero(small) - np.count_nonzero(large)) * MM_PER_PIXEL**2
    assert removed_mm2 == pytest.approx(4 * math.pi * (5**2 - 3**2), rel=0.03)
