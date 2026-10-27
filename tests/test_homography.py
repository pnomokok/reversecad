"""Tests for homography.py on a synthetic tilted scene where the true answer is known.

The scene is laid out in mm (a card and a 55.5 x 20 mm "key" 100 mm to its
left) and projected into a photo with a known perspective, like a camera
tilted sideways.
"""
import cv2
import numpy as np
import pytest

from homography import card_corners, card_homography, edge_differences, is_tilted, largest_contour, long_side_mm, to_mm
from measure import CARD_LONG_MM, CARD_SHORT_MM, card_scale
from measure import long_side_mm as naive_long_side_mm

CARD_MM = np.array([[0, 0], [CARD_SHORT_MM, 0], [CARD_SHORT_MM, CARD_LONG_MM], [0, CARD_LONG_MM]])
KEY_MM = np.array([[-110, 30], [-90, 30], [-90, 85.5], [-110, 85.5]])  # 20 x 55.5 mm
CANVAS = (2400, 1400)


def camera(tilt):
    """mm -> pixel projection, 10 px/mm; tilt > 0 makes the left side look larger."""
    # Third row: w = 1 + tilt * x, so points at negative x (left) get divided by w < 1.
    return np.array([[10, 0.3, 1500], [0.2, 10, 250], [tilt, 0, 1]])


def draw(points_mm, projection):
    pixels = cv2.perspectiveTransform(points_mm.reshape(-1, 1, 2).astype(np.float64), projection)
    mask = np.zeros(CANVAS[::-1], dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(pixels).astype(np.int32)], 1)
    return mask.astype(bool), pixels.reshape(-1, 2)


def test_corners_are_found_on_a_tilted_card():
    card_mask, true_corners = draw(CARD_MM, camera(tilt=0.0003))
    corners = card_corners(largest_contour(card_mask))
    assert np.abs(corners - true_corners).max() < 1.5


def test_straight_shot_is_not_tilted_and_tilted_shot_is():
    straight, _ = draw(CARD_MM, camera(tilt=0))
    tilted, _ = draw(CARD_MM, camera(tilt=0.0006))  # about 3.4% left vs right
    assert not is_tilted(edge_differences(card_corners(largest_contour(straight))))
    assert is_tilted(edge_differences(card_corners(largest_contour(tilted))))


def test_homography_recovers_key_length_where_simple_scale_fails():
    # This tilt gives only ~1.7% edge difference on the card, below the 2% warning,
    # yet the uncorrected key length is off by more than 2%: always correct, not only when warned.
    projection = camera(tilt=0.0003)
    card_mask, _ = draw(CARD_MM, projection)
    key_mask, _ = draw(KEY_MM, projection)

    homography, _ = card_homography(card_corners(largest_contour(card_mask)))
    corrected, _ = long_side_mm(to_mm(largest_contour(key_mask), homography))
    naive, _ = naive_long_side_mm(key_mask, card_scale(card_mask).mm_per_pixel)

    assert corrected == pytest.approx(55.5, rel=0.005)
    assert abs(naive - 55.5) / 55.5 > 0.02  # the uncorrected method is clearly off


def test_rectified_card_has_equal_opposite_edges():
    projection = camera(tilt=0.0003)
    card_mask, _ = draw(CARD_MM, projection)
    contour = largest_contour(card_mask)
    homography, _ = card_homography(card_corners(contour))
    after = edge_differences(card_corners(to_mm(contour, homography)))
    assert max(abs(d) for d in after) < 0.002
