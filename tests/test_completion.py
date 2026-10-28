"""Completion suggestions: reading Wonder's answer, and which completed programs pass the check."""
import pytest

from completion import check_completion, parse_answer
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
