"""Fallback outline: builds, passes its own checks; the checks catch every fault."""
import ast
import copy

import build_worker
from adapter_outline import check_adapter, fallback_source
from adapter_place import MIN_WALL_MM, profile_hole
from candidates import check_code
from design_intent import parameters

HOLES_A = [{"type": "circle", "center": [8.0, 8.0], "diameter": 6.0},
           {"type": "circle", "center": [72.0, 8.0], "diameter": 6.0},
           {"type": "circle", "center": [8.0, 32.0], "diameter": 6.0},
           {"type": "circle", "center": [72.0, 32.0], "diameter": 6.0}]
HOLES_B = [{"x": 10.0, "y": 20.0, "d": 5.5}, {"x": 70.0, "y": 20.0, "d": 5.5}]


def _build(source, **overrides):
    namespace = {}
    exec(compile(source, "fallback", "exec"), namespace)
    return build_worker.profile(namespace["build_part"](**overrides))


def _expected():
    return ([profile_hole(h) for h in HOLES_A], [{"circle": (h["x"], h["y"], h["d"])} for h in HOLES_B])


def test_fallback_passes_the_code_screen_and_imports_no_model():
    source = fallback_source(HOLES_A, HOLES_B, 3.0, "2 × M5 · 60 mm")
    assert check_code(source) == []
    imports = {alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
               for alias in node.names}
    assert imports == {"cadquery", "partkit"}
    params = dict(parameters(source))
    assert params == {"thickness": 3.0, "hole_diameter_a": 6.0, "hole_diameter_b": 5.5}


def test_fallback_builds_and_passes_its_own_checks():
    built = _build(fallback_source(HOLES_A, HOLES_B, 3.0, "2 × M5 · 60 mm"))
    assert built["solid_count"] == 1 and built["thickness"] == 3.0
    assert built["box"] == [3.0, 3.0, 77.0, 37.0]  # hole extents plus the 2 mm margin
    assert len(built["outline"]) > 4  # rounded corners, not a plain rectangle
    report = check_adapter(built, *_expected())
    assert report == {"ok": True, "reasons": [], "matched": "6/6", "min_margin_mm": 2.0}


def test_fallback_keeps_shaped_holes_of_pattern_a():
    shaped_a = HOLES_A[:2] + [{"type": "polyline", "points": [[30.0, 8.0], [50.0, 8.0], [50.0, 14.0], [30.0, 14.0]]}]
    built = _build(fallback_source(shaped_a, HOLES_B, 3.0, "pair"))
    expected_a = [profile_hole(h) for h in shaped_a]
    assert check_adapter(built, expected_a, _expected()[1])["ok"] is True


def test_a_thicker_fallback_still_passes():
    assert check_adapter(_build(fallback_source(HOLES_A, HOLES_B, 5.0, "pair")), *_expected())["ok"] is True


def test_moved_resized_missing_and_extra_holes_are_caught():
    good = _build(fallback_source(HOLES_A, HOLES_B, 3.0, "pair"))

    moved = copy.deepcopy(good)
    moved["holes"][0]["center"][0] += 1.0
    assert "1.00 mm off" in check_adapter(moved, *_expected())["reasons"][0]

    resized = copy.deepcopy(good)
    resized["holes"][0]["diameter"] += 1.0
    assert "instead of Ø6.00" in check_adapter(resized, *_expected())["reasons"][0]

    missing = copy.deepcopy(good)
    del missing["holes"][0]
    report = check_adapter(missing, *_expected())
    assert report["ok"] is False and "missing" in report["reasons"][0] and report["matched"] == "5/6"

    extra = copy.deepcopy(good)
    extra["holes"].append({"type": "circle", "center": [40.0, 20.0], "diameter": 3.0})
    assert "extra hole" in check_adapter(extra, *_expected())["reasons"][0]

    two_solids = dict(good, solid_count=2)
    assert "2 solids" in check_adapter(two_solids, *_expected())["reasons"][0]


def test_a_hole_too_close_to_the_edge_is_caught():
    good = _build(fallback_source(HOLES_A, HOLES_B, 3.0, "pair"))
    tight = copy.deepcopy(good)
    tight["outline"] = [[0.0, 0.0], [73.0, 0.0], [73.0, 40.0], [0.0, 40.0]]  # edge 1 mm past a hole centre
    report = check_adapter(tight, *_expected())
    assert report["ok"] is False and "(72.00, 8.00) is -2.00 mm from the edge" in report["reasons"][0]


def test_margins_are_measured_to_the_built_outline():
    assert adapter_margin(HOLES_B[0]) == MIN_WALL_MM


def adapter_margin(hole):
    built = _build(fallback_source(HOLES_A, HOLES_B, 3.0, "pair"))
    return check_adapter(built, *_expected())["min_margin_mm"]
