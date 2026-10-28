"""Break cues on synthetic broken parts (known damage) and on intact parts (no cues expected)."""
import numpy as np
import pytest

from break_cues import find_break_cues
from part_measurements import measure_part
from parts.broken_parts import BROKEN, make_broken_part
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette

SCALE = np.diag([0.1, 0.1, 1.0])


def cues_of(part, angle=8):
    """Cues from the measurement table of the part's top view, turned like a part lying on a table."""
    table = measure_part(render_top_silhouette(part.rotate((0, 0, 0), (0, 0, 1), angle), 0.1) > 0, SCALE)
    return find_break_cues(table)


def kinds(result):
    return sorted(cue["kind"] for cue in result["cues"])


@pytest.mark.parametrize("name", list("ABCDE"))
def test_intact_parts_show_no_break(name):
    result = cues_of(make_part(name))
    assert result["break_likely"] is False, result["cues"]


def test_chipped_corner_is_a_rough_edge_next_to_missing_material():
    result = cues_of(make_broken_part("A_chipped"))
    assert kinds(result) == ["missing_material", "rough_edge"]
    missing = next(c for c in result["cues"] if c["kind"] == "missing_material")
    assert missing["area_mm2"] == pytest.approx(12 * 10 / 2, rel=0.15)  # the broken-off triangle


def test_hole_never_drilled_is_a_gap_in_the_pattern():
    result = cues_of(make_broken_part("A_missing_hole"))
    assert kinds(result) == ["missing_hole"]
    cue = result["cues"][0]
    assert cue["material_fraction"] == 1.0 and cue["diameter_mm"] == pytest.approx(6, abs=0.2)
    # The other three holes are at (±32, ±12) from the center; the gap is the fourth position.
    assert np.abs(cue["expected_at_mm"]) == pytest.approx([32, 12], abs=0.3)


def test_break_through_a_hole_leaves_a_partial_hole():
    result = cues_of(make_broken_part("A_half_hole"))
    assert {"partial_hole", "rough_edge", "missing_material"} <= set(kinds(result))
    partial = next(c for c in result["cues"] if c["kind"] == "partial_hole")
    assert partial["outline_follows_circle_deg"] >= 120  # about half of the circle is still there


def test_snapped_tab_is_a_rough_edge_as_wide_as_the_tab():
    result = cues_of(make_broken_part("D_tab_broken"))
    assert kinds(result) == ["rough_edge"]
    assert result["cues"][0]["length_mm"] == pytest.approx(16, abs=1.5)


def test_every_broken_part_is_flagged():
    assert all(cues_of(make_broken_part(name))["break_likely"] for name in BROKEN)


def test_old_tables_without_the_detailed_outline_are_not_judged():
    assert find_break_cues({"outline": {}, "holes": []})["break_likely"] is None
