"""Tests for aligned_iou: alignment must forgive position, rotation, 180-degree
flips and mirroring, but never scale or shape differences."""
import cadquery as cq
import numpy as np
import pytest

from iou import aligned_iou
from parts.holed_plate import make_holed_plate
from render_silhouette import render_top_silhouette

MM_PER_PIXEL = 0.1


def render(workplane, mm_per_pixel=MM_PER_PIXEL):
    return render_top_silhouette(workplane, mm_per_pixel)


def shift(mask, right_px, down_px):
    """Move the mask inside a larger canvas (simulates a different position in the photo)."""
    return np.pad(mask, ((down_px, 0), (right_px, 0)))


def make_asymmetric_plate():
    """80 x 40 plate whose holes differ under both 180-degree rotation and mirroring.

    The symmetric holed plate looks the same flipped or mirrored, so it cannot
    prove the right variant is found; this one can.
    """
    plate = cq.Workplane("XY").box(80, 40, 3, centered=(True, True, False))
    for (x, y), diameter in [((25, 8), 10), ((-25, 8), 4), ((0, -10), 6)]:
        plate = plate.faces(">Z").workplane().pushPoints([(x, y)]).hole(diameter)
    return plate


@pytest.fixture(scope="module")
def plate_mask():
    return render(make_holed_plate())


@pytest.fixture(scope="module")
def asymmetric_mask():
    return render(make_asymmetric_plate())


def test_identical_mask_scores_one(plate_mask):
    result = aligned_iou(plate_mask, MM_PER_PIXEL, plate_mask, MM_PER_PIXEL)
    assert result.iou == pytest.approx(1.0)


def test_shifted_and_rotated_copy_scores_high(plate_mask):
    rotated = make_holed_plate().rotate((0, 0, 0), (0, 0, 1), 30)
    candidate = shift(render(rotated), 57, 23)
    result = aligned_iou(plate_mask, MM_PER_PIXEL, candidate, MM_PER_PIXEL)
    assert result.iou > 0.98


def test_different_pixel_scales_are_normalized(plate_mask):
    """Same part rendered at another mm/px (like a photo vs a render) still matches."""
    candidate = render(make_holed_plate(), mm_per_pixel=0.15)
    result = aligned_iou(plate_mask, MM_PER_PIXEL, candidate, 0.15)
    assert result.iou > 0.97


def test_rotated_180_is_found(asymmetric_mask):
    candidate = shift(np.rot90(asymmetric_mask, 2), 40, 15)
    result = aligned_iou(asymmetric_mask, MM_PER_PIXEL, candidate, MM_PER_PIXEL)
    assert result.iou > 0.98
    assert result.mirrored is False
    # The other variants are clearly worse, so trying them actually matters.
    assert sorted(result.variant_ious.values())[-2] < 0.97


def test_rotated_180_and_mirrored_is_found(asymmetric_mask):
    # Mirror left-right plus 180-degree rotation equals an up-down flip.
    candidate = shift(np.flipud(asymmetric_mask), 12, 70)
    result = aligned_iou(asymmetric_mask, MM_PER_PIXEL, candidate, MM_PER_PIXEL)
    assert result.iou > 0.98
    assert result.mirrored is True
    assert sorted(result.variant_ious.values())[-2] < 0.97


def test_scaled_up_10_percent_scores_clearly_lower():
    """Proves scale is not fitted: a 10% larger plate must not pass as a match."""
    plain = render(cq.Workplane("XY").box(80, 40, 3))
    larger = render(cq.Workplane("XY").box(88, 44, 3))
    result = aligned_iou(plain, MM_PER_PIXEL, larger, MM_PER_PIXEL)
    # Ideal value is 1 / 1.1^2 = 0.826.
    assert result.iou == pytest.approx(0.826, abs=0.01)


def test_scaled_up_10_percent_holed_plate_scores_even_lower(plate_mask):
    # Scaled holes also shift outward and stop overlapping, so IoU drops below 0.826.
    larger = make_holed_plate(length=88, width=44, thickness=3, hole_diameter=6.6, hole_inset=8.8)
    result = aligned_iou(plate_mask, MM_PER_PIXEL, render(larger), MM_PER_PIXEL)
    assert result.iou < 0.85


def test_different_outline_scores_low(plate_mask):
    square = make_holed_plate(length=40, width=40)
    result = aligned_iou(plate_mask, MM_PER_PIXEL, render(square), MM_PER_PIXEL)
    assert result.iou < 0.6


# Known weakness: small holes barely move IoU. These tests document it so the
# pipeline doesn't rely on IoU alone to check holes.

def test_missing_holes_only_drop_iou_slightly(plate_mask):
    no_holes = cq.Workplane("XY").box(80, 40, 3, centered=(True, True, False))
    result = aligned_iou(plate_mask, MM_PER_PIXEL, render(no_holes), MM_PER_PIXEL)
    # Ideal value is holed area / plain area = 3086.9 / 3200 = 0.965.
    assert result.iou == pytest.approx(0.965, abs=0.01)


def test_different_hole_layout_only_drops_iou_slightly(plate_mask):
    two_center_holes = (
        cq.Workplane("XY")
        .box(80, 40, 3, centered=(True, True, False))
        .faces(">Z")
        .workplane()
        .pushPoints([(-10, 0), (10, 0)])
        .hole(6)
    )
    result = aligned_iou(plate_mask, MM_PER_PIXEL, render(two_center_holes), MM_PER_PIXEL)
    # Ideal value is (3200 - 6 holes) / 3200 = 0.947.
    assert result.iou == pytest.approx(0.947, abs=0.01)
