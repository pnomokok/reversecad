"""Tests for part_measurements.py, refine_holes.py and the synthetic scenes (no API calls).

Uses the scenes' ground-truth masks, so it checks scene geometry, homography
and the measurement table without SAM in the loop.
"""
import cv2
import numpy as np
import pytest

from homography import card_corners, card_homography, largest_contour
from part_measurements import check_topology, compare_to_truth, measure_part
from parts.template_parts import make_part, part_truth
from refine_holes import refine_holes
from render_silhouette import render_top_silhouette
from synthetic_scene import DARK_PART, LIGHT_METAL, make_scene

MM_PER_PIXEL = 0.1
SCALE = np.diag([MM_PER_PIXEL, MM_PER_PIXEL, 1.0])  # render pixels -> mm


@pytest.mark.parametrize("name", ["A", "B", "C", "D", "E"])
def test_rendered_template_part_matches_its_truth(name):
    mask = render_top_silhouette(make_part(name).rotate((0, 0, 0), (0, 0, 1), 20), MM_PER_PIXEL) > 0
    table = measure_part(mask, SCALE)
    truth = part_truth(name)
    errors = compare_to_truth(table, truth)
    assert abs(errors["length_mm"]) < 0.3 and abs(errors["width_mm"]) < 0.3
    assert errors["vertex_count"] == 0 and errors["hole_count"] == 0
    for hole in errors["holes"]:
        assert hole["measured_shape"] == hole["true_shape"]
        assert hole["center_error_mm"] < 0.3 and abs(hole["diameter_error_mm"]) < 0.25
        if "length_error_mm" in hole:
            assert abs(hole["length_error_mm"]) < 0.3 and abs(hole["width_error_mm"]) < 0.3
    assert check_topology(table, truth) == (True, [])


def test_rectangular_hole_and_slot_are_told_apart():
    mask = render_top_silhouette(make_part("E").rotate((0, 0, 0), (0, 0, 1), 30), MM_PER_PIXEL) > 0
    holes = measure_part(mask, SCALE)["holes"]
    by_shape = {hole["shape"]: hole for hole in holes}
    assert set(by_shape) == {"rectangle", "slot"}
    rectangle, slot = by_shape["rectangle"], by_shape["slot"]
    assert (rectangle["length_mm"], rectangle["width_mm"]) == pytest.approx((16, 8), abs=0.3)
    assert (slot["length_mm"], slot["width_mm"]) == pytest.approx((20, 6), abs=0.3)
    # Both run along the part's length, whatever the part's angle in the image.
    assert abs(rectangle["angle_deg"]) < 2 and abs(slot["angle_deg"]) < 2
    assert all(len(hole["polygon_mm"]) >= 4 for hole in holes)


def test_round_holes_stay_circles():
    holes = measure_part(render_top_silhouette(make_part("B"), MM_PER_PIXEL) > 0, SCALE)["holes"]
    assert [hole["shape"] for hole in holes] == ["circle", "circle"]


def test_l_plate_corners_are_measured_in_mm():
    table = measure_part(render_top_silhouette(make_part("C"), MM_PER_PIXEL) > 0, SCALE)
    corners = np.abs(np.array(table["outline"]["polygon_mm"]))
    # The L's corners sit at |u| in {35, 15} and |v| in {25, 5} from the 70 x 50 box center.
    for u, v in corners:
        assert min(abs(u - 35), abs(u - 15)) < 0.3 and min(abs(v - 25), abs(v - 5)) < 0.3


def test_wrong_topology_is_reported():
    table = measure_part(render_top_silhouette(make_part("B"), MM_PER_PIXEL) > 0, SCALE)
    ok, reasons = check_topology(table, part_truth("C"))
    assert not ok and reasons


def _homography_and_filled(masks):
    homography, _ = card_homography(card_corners(largest_contour(masks["card"])))
    contours, _ = cv2.findContours(masks["part"].astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros(masks["part"].shape, dtype=np.uint8)
    cv2.drawContours(filled, contours, -1, 1, thickness=cv2.FILLED)
    return homography, filled > 0


@pytest.fixture(scope="module")
def light_scene():
    return make_scene(make_part("A"), LIGHT_METAL)


def test_synthetic_scene_measures_correctly_with_perfect_masks(light_scene):
    _, masks = light_scene
    homography, _ = _homography_and_filled(masks)
    table = measure_part(masks["part"], homography)
    errors = compare_to_truth(table, part_truth("A"))
    assert errors["hole_count"] == 0 and errors["vertex_count"] == 0
    assert abs(errors["length_mm"]) < 0.4 and abs(errors["width_mm"]) < 0.4
    assert max(abs(h["diameter_error_mm"]) for h in errors["holes"]) < 0.3
    assert max(h["center_error_mm"] for h in errors["holes"]) < 0.4
    # The card defines the mm frame, so the part lands where it was placed on the table.
    assert table["center_on_table_mm"] == pytest.approx([145.0, 27.0], abs=0.5)


@pytest.mark.parametrize("color", [LIGHT_METAL, DARK_PART], ids=["light part", "dark part"])
def test_refine_holes_recovers_holes_sam_filled_in(color):
    photo, masks = make_scene(make_part("A"), color)
    homography, filled = _homography_and_filled(masks)  # imitate SAM filling every hole
    refined, hole_count = refine_holes(photo, filled)
    errors = compare_to_truth(measure_part(refined, homography), part_truth("A"))
    assert hole_count == 4
    assert max(abs(h["diameter_error_mm"]) for h in errors["holes"]) < 0.3
    assert max(h["center_error_mm"] for h in errors["holes"]) < 0.4
