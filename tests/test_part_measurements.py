"""Tests for part_measurements.py and the synthetic scene (no API calls).

Uses the scene's ground-truth masks, so it checks scene geometry, homography
and the measurement table without SAM in the loop.
"""
import cv2
import numpy as np
import pytest

from homography import card_corners, card_homography, largest_contour
from part_measurements import compare_to_truth, measure_part
from parts.holed_plate import make_holed_plate
from refine_holes import refine_holes
from render_silhouette import render_top_silhouette
from synthetic_scene import make_scene


def test_measures_plate_rendered_directly_in_mm():
    mm_per_pixel = 0.1
    mask = render_top_silhouette(make_holed_plate().rotate((0, 0, 0), (0, 0, 1), 20), mm_per_pixel)
    pixels_to_mm = np.diag([mm_per_pixel, mm_per_pixel, 1.0])
    table = measure_part(mask > 0, pixels_to_mm)
    assert table["outline"]["length_mm"] == pytest.approx(80, abs=0.3)
    assert table["outline"]["width_mm"] == pytest.approx(40, abs=0.3)
    assert table["hole_count"] == 4
    for hole in table["holes"]:
        assert hole["diameter_mm"] == pytest.approx(6, abs=0.25)
        u, v = hole["center_from_part_center_mm"]
        assert (abs(u), abs(v)) == pytest.approx((32, 12), abs=0.3)


@pytest.fixture(scope="module")
def scene():
    return make_scene()


def test_synthetic_scene_measures_correctly_with_perfect_masks(scene):
    _, masks, truth = scene
    homography, _ = card_homography(card_corners(largest_contour(masks["card"])))
    table = measure_part(masks["plate"], homography)
    errors = compare_to_truth(table, truth["plate"])
    assert errors["hole_count"] == 0
    assert abs(errors["length_mm"]) < 0.4 and abs(errors["width_mm"]) < 0.4
    assert max(abs(e) for e in errors["hole_diameter_mm"]) < 0.3
    assert max(errors["hole_center_mm"]) < 0.4
    # The card defines the mm frame, so the plate lands where it was placed on the table.
    assert table["center_on_table_mm"] == pytest.approx(truth["plate"]["center_on_table_mm"], abs=0.5)


def test_refine_holes_recovers_holes_sam_filled_in(scene):
    photo, masks, truth = scene
    # Imitate SAM filling the holes: keep only the plate's outer outline, filled.
    contours, _ = cv2.findContours(masks["plate"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros(masks["plate"].shape, dtype=np.uint8)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)

    refined, hole_count = refine_holes(photo, filled > 0)
    homography, _ = card_homography(card_corners(largest_contour(masks["card"])))
    errors = compare_to_truth(measure_part(refined, homography), truth["plate"])
    assert hole_count == 4
    assert max(abs(e) for e in errors["hole_diameter_mm"]) < 0.3
    assert max(errors["hole_center_mm"]) < 0.4
