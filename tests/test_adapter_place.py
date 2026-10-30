"""Placement: exact walls, the fixed candidate order, and the cases that cannot place."""
import pytest

from adapter_pattern import PRESETS
from adapter_place import MIN_WALL_MM, hole_wall, place_pattern

PROFILE = {"box": [0.0, 0.0, 80.0, 40.0],
           "holes": [{"type": "circle", "center": [8.0, 8.0], "diameter": 6.0},
                     {"type": "circle", "center": [72.0, 8.0], "diameter": 6.0},
                     {"type": "circle", "center": [8.0, 32.0], "diameter": 6.0},
                     {"type": "circle", "center": [72.0, 32.0], "diameter": 6.0}]}


def test_min_wall_is_a_single_named_constant():
    assert MIN_WALL_MM == 2.0


def test_wall_between_circles_is_signed():
    a = {"circle": (0.0, 0.0, 6.0)}
    assert hole_wall(a, {"circle": (10.0, 0.0, 6.0)}) == pytest.approx(4.0)
    assert hole_wall(a, {"circle": (6.0, 0.0, 6.0)}) == pytest.approx(0.0)  # touching
    assert hole_wall(a, {"circle": (4.0, 0.0, 6.0)}) == pytest.approx(-2.0)  # overlapping
    assert hole_wall(a, {"circle": (0.0, 0.0, 4.0)}) == pytest.approx(-5.0)  # nested


def test_wall_with_shaped_holes_is_exact():
    rect = {"polygon": [(-10.0, -4.0), (10.0, -4.0), (10.0, 4.0), (-10.0, 4.0)]}
    assert hole_wall(rect, {"circle": (16.0, 0.0, 6.0)}) == pytest.approx(3.0)
    assert hole_wall(rect, {"circle": (0.0, 0.0, 4.0)}) < 0  # a hole inside the opening
    other = {"polygon": [(15.0, -4.0), (35.0, -4.0), (35.0, 4.0), (15.0, 4.0)]}
    assert hole_wall(rect, other) == pytest.approx(5.0)


def test_a_preset_places_centred_on_a_plate():
    placed = place_pattern(PROFILE, dict(PRESETS[0]))
    assert placed["candidate"] == "centred"
    assert [(h["x"], h["y"], h["d"]) for h in placed["holes_b"]] == [(10.0, 20.0, 5.5), (70.0, 20.0, 5.5)]
    assert placed["walls"]["min"] == pytest.approx(6.416, abs=0.001)
    assert placed["walls"] == {"aa": 18.0, "ab": pytest.approx(6.416, abs=0.001), "bb": 54.5,
                               "min": pytest.approx(6.416, abs=0.001)}


def test_rotation_is_tried_when_centred_overlaps():
    profile = {"box": [-20.0, -20.0, 20.0, 20.0],
               "holes": [{"type": "circle", "center": [-10.0, 0.0], "diameter": 6.0},
                         {"type": "circle", "center": [10.0, 0.0], "diameter": 6.0}]}
    pattern = {"holes": [{"x": -10.0, "y": 0.0, "d": 6.0}, {"x": 10.0, "y": 0.0, "d": 6.0}], "label": "pair"}
    placed = place_pattern(profile, pattern)
    assert placed["candidate"] == "centred + rotated 90°"
    assert [(h["x"], h["y"]) for h in placed["holes_b"]] == [(0.0, -10.0), (0.0, 10.0)]


def test_offsets_run_along_the_long_axis():
    wide = {"box": [-40.0, -10.0, 40.0, 10.0],
            "holes": [{"type": "circle", "center": [0.0, 0.0], "diameter": 6.0}]}
    single = {"holes": [{"x": 0.0, "y": 0.0, "d": 6.0}], "label": "single"}
    placed = place_pattern(wide, single)
    assert placed["candidate"] == "offset +10 mm"  # centred and rotated both overlap A
    assert [(h["x"], h["y"]) for h in placed["holes_b"]] == [(10.0, 0.0)]
    tall = {"box": [-10.0, -40.0, 10.0, 40.0], "holes": wide["holes"]}
    assert place_pattern(tall, single)["holes_b"] == [{"x": 0.0, "y": 10.0, "d": 6.0}]


def test_patterns_no_rigid_motion_can_fix_do_not_place():
    far = {"box": [0.0, 0.0, 200.0, 200.0],
           "holes": [{"type": "circle", "center": [100.0, 100.0], "diameter": 6.0}]}
    thin = {"holes": [{"x": -3.0, "y": 0.0, "d": 5.5}, {"x": 3.0, "y": 0.0, "d": 5.5}], "label": "thin"}
    assert place_pattern(far, thin) is None  # B-B wall 0.5 mm wherever it goes
    broken = {"box": [0.0, 0.0, 80.0, 40.0],
              "holes": [{"type": "circle", "center": [40.0, 20.0], "diameter": 6.0},
                        {"type": "circle", "center": [41.0, 20.0], "diameter": 6.0}]}
    assert place_pattern(broken, dict(PRESETS[0])) is None  # A-A already overlap
