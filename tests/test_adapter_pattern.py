"""Pattern B input: presets are valid, validation rejects bad patterns, the model is mocked."""
import pytest

from adapter_pattern import (
    EXAMPLE, ISO_273_MEDIUM, PATTERN_MAX_DIAMETER_MM, PATTERN_MAX_EXTENT_MM, PATTERN_MAX_HOLES,
    PRESETS, interpret_pattern, parse_pattern_answer, summarize_pattern, validate_pattern,
)


def test_iso_table_is_the_medium_series():
    assert ISO_273_MEDIUM == {"M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6}


@pytest.mark.parametrize("preset", PRESETS, ids=[p["id"] for p in PRESETS])
def test_presets_are_valid_and_summarize_to_their_labels(preset):
    pattern, error = validate_pattern(preset)
    assert error is None
    assert summarize_pattern(pattern) == {"2xM5_60": "2 holes · Ø5.5 · 60 mm apart",
                                          "4xM4_40x40": "4 holes · Ø4.5 · 40 × 40 mm",
                                          "4xM3_30x30": "4 holes · Ø3.4 · 30 × 30 mm"}[preset["id"]]


def test_a_good_pattern_is_sorted_and_rounded():
    pattern, error = validate_pattern(
        {"holes": [{"x": 30.0004, "y": 0, "d": 5.5}, {"x": -30, "y": 0.0, "d": 5.5}], "label": "  pair  "})
    assert error is None
    assert pattern == {"holes": [{"x": -30.0, "y": 0.0, "d": 5.5}, {"x": 30.0, "y": 0.0, "d": 5.5}], "label": "pair"}


def test_bad_patterns_are_rejected_with_a_reason():
    hole = {"x": 0.0, "y": 0.0, "d": 5.5}
    cases = [
        ({"holes": [], "label": "empty"}, "1-12 holes"),
        ({"holes": [dict(hole, x=float(10 * j)) for j in range(PATTERN_MAX_HOLES + 1)],
          "label": "many"}, "1-12 holes"),
        ({"holes": [dict(hole, d=0.0)], "label": "zero"}, "outside 1-50 mm"),
        ({"holes": [dict(hole, d=-5.5)], "label": "negative"}, "outside 1-50 mm"),
        ({"holes": [dict(hole, d=PATTERN_MAX_DIAMETER_MM + 1)], "label": "huge"}, "outside 1-50 mm"),
        ({"holes": [dict(hole, x=PATTERN_MAX_EXTENT_MM + 1)], "label": "far"}, "outside ±200 mm"),
        ({"holes": [dict(hole, x=True)], "label": "bool"}, "numeric x, y and d"),
        ({"holes": [{"x": 0.0, "y": 0.0}], "label": "no d"}, "numeric x, y and d"),
        ({"holes": [hole], "label": "  "}, "short label"),
        ({"holes": [hole], "label": "x" * 81}, "short label"),
        ({"holes": [hole]}, "short label"),
        ({"label": "no holes"}, '{"holes"'),
        ("just text", '{"holes"'),
    ]
    for data, reason in cases:
        pattern, error = validate_pattern(data)
        assert pattern is None and reason in error, data


def test_touching_holes_pass_but_overlapping_holes_are_rejected():
    touching = {"holes": [{"x": -2.75, "y": 0, "d": 5.5}, {"x": 2.75, "y": 0, "d": 5.5}], "label": "touching"}
    assert validate_pattern(touching)[1] is None
    overlapping = {"holes": [{"x": -2.7, "y": 0, "d": 5.5}, {"x": 2.7, "y": 0, "d": 5.5}], "label": "overlap"}
    pattern, error = validate_pattern(overlapping)
    assert pattern is None and "overlap" in error


def test_summaries_are_computed_from_the_holes():
    single, _ = validate_pattern({"holes": [{"x": 3.0, "y": 4.0, "d": 6.6}], "label": "one"})
    assert summarize_pattern(single) == "1 hole · Ø6.6 · single hole"
    mixed, _ = validate_pattern({"holes": [{"x": 0, "y": 0, "d": 3.4}, {"x": 10, "y": 0, "d": 6.6}], "label": "mixed"})
    assert summarize_pattern(mixed) == "2 holes · Ø3.4–Ø6.6 · 10 mm apart"


def test_model_answers_are_parsed_or_refused_without_guessing():
    pattern, error = parse_pattern_answer('```json\n{"holes": [{"x": -30, "y": 0, "d": 5.5},'
                                          ' {"x": 30, "y": 0, "d": 5.5}], "label": "pair"}\n```')
    assert error is None and summarize_pattern(pattern) == "2 holes · Ø5.5 · 60 mm apart"
    assert parse_pattern_answer("NO PATTERN") == (None, f"no hole pattern in that text (try {EXAMPLE})")
    for bad in ("make it prettier", '{"holes": []}', '{"holes": [{"x": 0, "y": 0, "d": -1}], "label": "x"}', ""):
        assert parse_pattern_answer(bad)[0] is None


class _FakeCompletions:
    def __init__(self, text):
        self.text = text

    def create(self, **kwargs):
        assert kwargs["reasoning_effort"] == "low"

        class Message:  # the fields interpret_pattern reads
            content = self.text

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

            def model_dump(self):
                return {"usage": {}}

        return Response()


class _FakeClient:
    def __init__(self, text):
        self.chat = type("chat", (), {"completions": _FakeCompletions(text)})()


def test_interpret_uses_the_mocked_model_and_validates_its_answer():
    answer = interpret_pattern("2 x M5, 60 apart", client=_FakeClient(
        '{"holes": [{"x": -30, "y": 0, "d": 5.5}, {"x": 30, "y": 0, "d": 5.5}], "label": "2 x M5"}'))
    assert answer["summary"] == "2 holes · Ø5.5 · 60 mm apart"
    with pytest.raises(RuntimeError, match="could not read"):
        interpret_pattern("make it prettier", client=_FakeClient("make it prettier"))
