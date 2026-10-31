"""Deterministic restored-hole position: arc fit, neighbour alignment, mirror fallback."""
import numpy as np
import pytest

from completion import apply_restored_positions
from restored_hole import (align_to_neighbours, fit_arc_center, median_hole_radius,
                           restore_hole_position)

TRUTH = (32.0, 12.0)
CLAIM = (34.0, 13.0)  # a mirror-ish guess, 2.2 mm off
HOLES = [
    {"center_from_part_center_mm": [-32.0, 12.0], "diameter_mm": 6.0},
    {"center_from_part_center_mm": [-32.0, -12.0], "diameter_mm": 6.2},
    {"center_from_part_center_mm": [32.0, -12.0], "diameter_mm": 5.8},
]


def _rectangle(step=1):
    points = []
    for x in range(-40, 41, step):
        points += [[x, 20], [x, -20]]
    for y in range(-20, 21, step):
        points += [[40, y], [-40, y]]
    return points


def _arc(from_deg, to_deg, step_deg=2):
    return [[TRUTH[0] + 3 * np.cos(np.radians(d)), TRUTH[1] + 3 * np.sin(np.radians(d))]
            for d in np.arange(from_deg, to_deg + 1, step_deg)]


def _table(contour):
    return {"holes": HOLES, "outline": {"contour_mm": contour}}


def test_half_hole_arc_fits_within_tolerance():
    """A clean remaining half arc (180°) fits its true center despite edge clutter in-window."""
    contour = _rectangle() + _arc(80, 260)
    (x, y), coverage = fit_arc_center(contour, CLAIM, 3.0)
    assert coverage >= 60
    assert abs(x - TRUTH[0]) < 0.1 and abs(y - TRUTH[1]) < 0.1
    (rx, ry), method = restore_hole_position(_table(contour), CLAIM)
    assert method == "arc fit"
    assert abs(rx - TRUTH[0]) < 0.1 and abs(ry - TRUTH[1]) < 0.1


def test_tiny_arc_falls_through_to_alignment():
    """A 30° leftover refuses the fit; the row/column neighbours place the hole."""
    contour = _rectangle() + _arc(175, 205)
    assert fit_arc_center(contour, CLAIM, 3.0) is None
    (x, y), method = restore_hole_position(_table(contour), CLAIM)
    assert method == "aligned with neighbours"
    assert (x, y) == (32.0, 12.0)


def test_alignment_reads_rows_and_columns():
    """Nearest column's x and nearest row's y, like the asymmetric hand-punched layout."""
    holes = [{"center_from_part_center_mm": "-42.66 39.16", "diameter_mm": 6.1},
             {"center_from_part_center_mm": "-40.8 -38.36", "diameter_mm": 6.1},
             {"center_from_part_center_mm": "38.76 -37.36", "diameter_mm": 6.1}]
    assert align_to_neighbours(holes, (42.66, 39.16)) == (38.76, 39.16)


def test_lone_neighbour_keeps_the_mirrored_claim():
    """One hole cannot give both row and column: the claim is kept as mirrored."""
    table = {"holes": [{"center_from_part_center_mm": [0.0, 0.0], "diameter_mm": 6.0}],
             "outline": {"contour_mm": [[-40, -20], [40, -20], [40, 20], [-40, 20]]}}
    assert align_to_neighbours(table["holes"], (20.0, 0.0)) is None
    assert restore_hole_position(table, (20.0, 0.0)) == ((20.0, 0.0), "mirrored")


def test_median_hole_radius():
    assert median_hole_radius({"holes": HOLES}) == 3.0
    assert median_hole_radius({"holes": []}) is None


def _part(name, value, basis="measured"):
    return {"name": name, "value": value, "basis": basis, "evidence": None, "question": None}


def test_suggestion_pair_takes_the_fitted_position():
    """The restored pair is overridden with the arc fit (Measured); the rest is untouched."""
    parts = [_part("restored_hole_x", 34.0, "estimated"), _part("restored_hole_y", 13.0, "estimated"),
             _part("hole_x", -32.0), _part("hole_y", 12.0), _part("length", 80.0)]
    checked, defaults = apply_restored_positions(parts, _table(_rectangle() + _arc(80, 260)))
    by_name = {part["name"]: part for part in checked}
    assert by_name["restored_hole_x"]["value"] == pytest.approx(32.0, abs=0.1)
    assert by_name["restored_hole_y"]["value"] == pytest.approx(12.0, abs=0.1)
    assert by_name["restored_hole_x"]["basis"] == "measured"
    assert by_name["restored_hole_x"]["method"] == "arc fit"
    assert by_name["hole_x"]["value"] == -32.0 and "method" not in by_name["hole_x"]
    assert by_name["length"] == parts[4]
    assert defaults == {"restored_hole_x": by_name["restored_hole_x"]["value"],
                        "restored_hole_y": by_name["restored_hole_y"]["value"]}


def test_parts_without_pairs_are_untouched():
    """Completions with no restored hole (like D_tab_broken) pass through unchanged."""
    parts = [_part("tab_extension", 12.78, "estimated"), _part("tab_hole_diameter", 10.05, "optional")]
    checked, defaults = apply_restored_positions(parts, _table(_rectangle()))
    assert checked == parts and defaults == {}
