"""Completion suggestions: reading Wonder's answer, and which completed programs pass the check."""
import json

import pytest

from completion import check_completion, parse_answer, verify_parts
from webapp import replay
from webapp.builder import Builder

WINNER = '''import partkit as pk


def build_part(length=80.0, width=40.0, thickness=3.0, hole_diameter=6.0):
    part = pk.plate(length, width, thickness)
    return pk.hole_pattern(part, [(-32, -12), (32, -12), (-32, 12)], hole_diameter)
'''

ADDS_THE_MISSING_HOLE = WINNER.replace("(-32, 12)]", "(-32, 12), (32, 12)]")
ADDS_A_TAB = WINNER.replace("    return pk.hole_pattern", "    part = pk.tab(part, (0, 20), 12, 16, 90)\n    return pk.hole_pattern")
CUTS_THE_PLATE_IN_HALF = WINNER.replace("pk.plate(length, width, thickness)", "pk.plate(length / 2, width, thickness)")


@pytest.fixture(scope="module")
def builder():
    builder = Builder()
    yield builder
    builder.close()


def write(tmp_path, name, code):
    path = tmp_path / f"{name}.py"
    path.write_text(code, encoding="utf-8")
    return path


def test_answer_fields_are_read():
    answer = parse_answer("BROKEN: yes\nSUGGESTION: add the fourth hole (hole_pattern)\n"
                          "RATIONALE: three of four mirrored holes exist.\n```python\nprint(1)\n```")
    assert answer == {"broken": True, "suggestion": "add the fourth hole (hole_pattern)",
                      "rationale": "three of four mirrored holes exist.", "parts": [], "code": "print(1)\n"}
    assert parse_answer("BROKEN: no\nSUGGESTION: none\nRATIONALE: designed this way.")["broken"] is False


@pytest.mark.parametrize("code, ok", [(ADDS_THE_MISSING_HOLE, True), (ADDS_A_TAB, True),
                                      (CUTS_THE_PLATE_IN_HALF, False), (WINNER, False)])
def test_a_completion_may_add_or_drill_but_not_take_away_the_part(tmp_path, builder, code, ok):
    winner = write(tmp_path, "winner", WINNER)
    result = check_completion(write(tmp_path, "completed", code), winner, tmp_path, builder)
    assert result["ok"] is ok, result
    if code is ADDS_A_TAB:
        assert result["added_volume_mm3"] > 0 and (tmp_path / "added.stl").exists()


def test_parts_say_what_is_measured_estimated_or_optional():
    answer = parse_answer(
        'BROKEN: yes\nSUGGESTION: restore the tab\nRATIONALE: rough edge.\n'
        'PARTS: [{"name": "tab_width", "value": 15, "basis": "measured", "evidence": "rough edge 14.4 mm"}, '
        '{"name": "tab_length", "value": 12.8, "basis": "estimated", "question": "How far did it stick out?"}, '
        '{"name": "tab_hole_diameter", "value": 6, "basis": "optional", "question": "Was there a hole?"}, '
        '{"name": "bad", "value": "x", "basis": "measured"}]\n```python\npass\n```')
    assert [(p["name"], p["basis"]) for p in answer["parts"]] == [
        ("tab_width", "measured"), ("tab_length", "estimated"), ("tab_hole_diameter", "optional")]
    assert answer["parts"][1]["question"] == "How far did it stick out?" and answer["code"] == "pass\n"
    assert parse_answer("BROKEN: no")["parts"] == []


BROKEN_TABLE = {"holes": [
    {"center_from_part_center_mm": [-42.66, 39.16], "diameter_mm": 6.17},
    {"center_from_part_center_mm": [-40.8, -38.36], "diameter_mm": 6.16},
    {"center_from_part_center_mm": [38.76, -37.36], "diameter_mm": 6.03},
]}
WINNER_PARAMS = {"length": 107.51, "width": 97.19, "thickness": 3.0, "hole_diameter": 6.11,
                 "notch_radius": 4.06, "chamfer_top": 25.33, "chamfer_side": 26.14}


def _part(name, value, basis="measured"):
    return {"name": name, "value": value, "basis": basis, "evidence": None, "question": None}


def test_mirrored_hole_position_is_estimated_not_measured():
    """A hole mirrored across the axis matches no measured hole: both coordinates drop."""
    parts = [_part("restored_hole_x", 42.66), _part("restored_hole_y", 39.16)]
    checked = verify_parts(parts, BROKEN_TABLE, WINNER_PARAMS)
    assert [(p["name"], p["basis"]) for p in checked] == [
        ("restored_hole_x", "estimated"), ("restored_hole_y", "estimated")]
    assert all(p["demoted_from"] == "measured" for p in checked)


def test_copied_winner_parameter_and_diameter_stay_measured():
    parts = [_part("chamfer_top", 25.33), _part("hole_diameter", 6.11), _part("tab_hole_diameter", 6.16)]
    assert [p["basis"] for p in verify_parts(parts, BROKEN_TABLE, WINNER_PARAMS)] == ["measured"] * 3


def test_position_on_a_measured_hole_stays_measured():
    parts = [_part("hole_x", -42.66), _part("hole_y", 39.16)]
    assert [p["basis"] for p in verify_parts(parts, BROKEN_TABLE, WINNER_PARAMS)] == ["measured"] * 2


def test_lone_coordinate_and_unbacked_value_are_demoted():
    parts = [_part("tab_tip_x", 60.0), _part("tab_length", 12.8)]
    assert [p["basis"] for p in verify_parts(parts, BROKEN_TABLE, WINNER_PARAMS)] == ["estimated"] * 2


def test_estimated_and_optional_are_never_touched():
    parts = [_part("tab_length", 12.8, "estimated"), _part("add_hole", 6.0, "optional")]
    assert verify_parts(parts, BROKEN_TABLE, WINNER_PARAMS) == parts


def test_string_hole_centers_are_read():
    table = {"holes": [{"center_from_part_center_mm": "-42.66 39.16", "diameter_mm": 6.11}]}
    parts = [_part("hole_x", -42.66), _part("hole_y", 39.16)]
    assert [p["basis"] for p in verify_parts(parts, table, {})] == ["measured"] * 2


def test_stored_runs_are_rechecked_on_read(tmp_path, monkeypatch):
    """An old suggestion with a mirrored hole under Measured shows it under Estimated."""
    run = tmp_path / "broken"
    (run / "6_completion").mkdir(parents=True)
    (run / "3_measurements.json").write_text(json.dumps({"table": BROKEN_TABLE}), encoding="utf-8")
    (run / "6_completion" / "completion.json").write_text(json.dumps({
        "winner": "winner.py", "valid": True,
        "parts": [_part("restored_hole_x", 42.66), _part("restored_hole_y", 39.16),
                  _part("chamfer_top", 25.33)]}), encoding="utf-8")
    (run / "round").mkdir()
    (run / "round" / "winner.py").write_text(
        "def build_part(chamfer_top=25.33, hole_diameter=6.11):\n    pass\n", encoding="utf-8")
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    parts = replay.completion("broken")["parts"]
    assert [(p["name"], p["basis"]) for p in parts] == [
        ("restored_hole_x", "estimated"), ("restored_hole_y", "estimated"), ("chamfer_top", "measured")]
