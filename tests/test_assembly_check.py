"""Assembly check and Slotted hole style, without calling any model.

Pure geometry first (screw rule, slot walls, error shift, mating transform), then the endpoints
on the A_light sample with a preset pattern (fallback outline, stand-in plate): Exact +
as-measured passes with zero interference, Exact + measured error blocks, Slotted + error passes.
"""
import json
import math

import pytest
from fastapi.testclient import TestClient

import adapter_pattern
import assembly_check
from assembly_check import SHIFT_MM
from webapp import replay, server
from webapp.server import app

client = TestClient(app)
PRESET = adapter_pattern.PRESETS[0]  # 2 x M5, 60 mm apart
A_HOLES = [{"circle": (x, y, 6.0)} for x in (-32.0, 32.0) for y in (-12.0, 12.0)]
B_HOLES = [{"x": -30.0, "y": 0.0, "d": 5.5}, {"x": 30.0, "y": 0.0, "d": 5.5}]
OUTLINE = [(-46.0, -25.0), (46.0, -25.0), (46.0, 25.0), (-46.0, 25.0)]


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    """Samples only and no API keys, as in the online demo."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def test_screw_default_is_the_largest_fitting_clearance():
    assert assembly_check.screw_for_diameter(6.0) == "M5"
    assert assembly_check.screw_for_diameter(5.5) == "M5"
    assert assembly_check.screw_for_diameter(5.49) == "M4"
    assert assembly_check.screw_for_diameter(3.4) == "M3"
    assert assembly_check.screw_for_diameter(3.39) is None
    assert assembly_check.screw_for_diameter(50.0) == "M6"


def test_pattern_long_axis_prefers_x_on_ties():
    assert assembly_check.pattern_long_axis([(-30.0, 0.0), (30.0, 0.0)]) == 0.0
    assert assembly_check.pattern_long_axis([(0.0, -30.0), (0.0, 30.0)]) == 90.0
    assert assembly_check.pattern_long_axis([(5.0, 5.0)]) == 0.0
    assert assembly_check.pattern_long_axis([(-20.0, -20.0), (20.0, 20.0)]) == 0.0


def test_error_shift_grows_the_spacing_by_shift_mm():
    moved = assembly_check.error_shifted_centers([[-30.0, 0.0], [30.0, 0.0]], 0.0)
    assert moved[1][0] - moved[0][0] == pytest.approx(60.0 + SHIFT_MM)
    assert moved[0][1] == moved[1][1] == 0.0
    moved = assembly_check.error_shifted_centers([[0.0, -20.0], [0.0, 20.0]], 90.0)
    assert moved[1][1] - moved[0][1] == pytest.approx(40.0 + SHIFT_MM)


def test_slot_polygon_is_a_capsule_of_length_by_width():
    points = assembly_check.slot_polygon((10.0, 0.0), 8.56, 6.0, 0.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    assert (min(xs), max(xs)) == pytest.approx((10.0 - 8.56 / 2, 10.0 + 8.56 / 2))
    assert (min(ys), max(ys)) == pytest.approx((-3.0, 3.0))
    points = assembly_check.slot_polygon((0.0, 0.0), 8.0, 5.0, 90.0)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    assert max(xs) - min(xs) == pytest.approx(5.0) and max(ys) - min(ys) == pytest.approx(8.0)


def test_slotted_walls_pass_when_slots_fit():
    specs, error = assembly_check.check_slotted_walls(OUTLINE, A_HOLES, B_HOLES)
    assert error is None
    assert [s["length"] for s in specs["a"]] == [pytest.approx(6.0 + 2 * SHIFT_MM)] * 4
    assert [s["length"] for s in specs["b"]] == [pytest.approx(5.5 + 2 * SHIFT_MM)] * 2
    assert all(s["angle"] == 0.0 for s in specs["a"] + specs["b"])
    assert [s["id"] for s in specs["a"]] == ["A1", "A2", "A3", "A4"]


def test_slotted_walls_name_the_broken_wall():
    close = [{"x": -32.0, "y": -9.0, "d": 5.5}, {"x": 32.0, "y": 9.0, "d": 5.5}]
    specs, error = assembly_check.check_slotted_walls(OUTLINE, A_HOLES, close)
    assert specs is None and "A–B wall" in error and "keeping Exact" in error


def test_slotted_walls_name_the_broken_margin():
    tight = [(-36.0, -25.0), (36.0, -25.0), (36.0, 25.0), (-36.0, 25.0)]
    specs, error = assembly_check.check_slotted_walls(tight, A_HOLES, B_HOLES)
    assert specs is None and "edge margin" in error and "keeping Exact" in error


def test_placement_transform_prefers_the_stored_one():
    placement = {"transform": {"dx": 1.0, "dy": 2.0, "rotated90": True}, "holes_b": []}
    assert assembly_check.placement_transform(placement, PRESET) == (1.0, 2.0, True)


def test_placement_transform_derives_zero_and_ninety():
    pattern = {"holes": [{"x": -30.0, "y": 0.0, "d": 5.5}, {"x": 30.0, "y": 0.0, "d": 5.5}]}
    plain = {"holes_b": [{"x": -29.0, "y": 1.0, "d": 5.5}, {"x": 31.0, "y": 1.0, "d": 5.5}]}
    assert assembly_check.placement_transform(plain, pattern) == (1.0, 1.0, False)
    turned = {"holes_b": [{"x": 1.0, "y": -29.0, "d": 5.5}, {"x": 1.0, "y": 31.0, "d": 5.5}]}
    assert assembly_check.placement_transform(turned, pattern) == (1.0, 1.0, True)
    with pytest.raises(ValueError):
        assembly_check.placement_transform({"holes_b": [{"x": 0.0, "y": 0.0, "d": 5.5}]}, pattern)


def test_stand_in_is_a_plain_rectangle_around_pattern_b():
    table, thickness = assembly_check.stand_in_table(B_HOLES, 3.0)
    assert thickness == 3.0 and len(table["holes"]) == 2
    xs = [p[0] for p in table["outline"]["polygon_mm"]]
    ys = [p[1] for p in table["outline"]["polygon_mm"]]
    assert (min(xs), max(xs)) == (-30.0 - 5.5 / 2 - 2.0, 30.0 + 5.5 / 2 + 2.0)
    assert (min(ys), max(ys)) == (-5.5 / 2 - 2.0, 5.5 / 2 + 2.0)


def test_mating_table_moves_outline_and_holes_by_the_placement():
    measured = {"outline": {"polygon_mm": [[-40.0, -20.0], [40.0, -20.0], [40.0, 20.0], [-40.0, 20.0]]},
                "holes": [{"shape": "circle", "center_from_part_center_mm": [-30.0, 0.0], "diameter_mm": 5.5},
                          {"shape": "circle", "center_from_part_center_mm": [30.0, 0.0], "diameter_mm": 5.5}]}
    mating = {"outline_polygon_mm": measured["outline"]["polygon_mm"], "outline_mm": [80.0, 40.0]}
    placement = {"holes_b": B_HOLES,
                 "transform": {"dx": 5.0, "dy": -7.0, "rotated90": False}}
    table, thickness = assembly_check.mating_table(measured, mating, placement, PRESET, 4.0)
    assert thickness == 4.0
    assert table["outline"]["polygon_mm"][0] == [-35.0, -27.0]
    assert [h["center_from_part_center_mm"] for h in table["holes"]] == [[-25.0, -7.0], [35.0, -7.0]]


def _outline_body(**overrides):
    body = {"base": {}, "pattern": PRESET, "outline": "fallback"}
    body.update(overrides)
    return body


def _searched():
    assert client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body()).status_code == 200


def _assembly_body(style="exact", error="as_measured", **overrides):
    body = {**_outline_body(), "parameters": {}, "hole_style": style, "error_case": error}
    body.update(overrides)
    return body


def test_slotted_variant_needs_a_searched_outline_first():
    thin = {"holes": [{"x": -3.0, "y": 0.0, "d": 5.5}, {"x": 3.0, "y": 0.0, "d": 5.5}], "label": "thin"}
    answer = client.post("/api/runs/A_light/matching/adapter/slotted", json=_outline_body(pattern=thin))
    assert answer.status_code == 404 and "outline search first" in answer.json()["detail"]


def test_slotted_variant_keeps_the_outline_with_slot_widths():
    _searched()
    for path in server.MATCHING_DIR.glob("slotted_*"):
        path.unlink()
    first = client.post("/api/runs/A_light/matching/adapter/slotted", json=_outline_body())
    assert first.status_code == 200
    answer = first.json()
    assert answer["hole_style"] == "slotted" and answer["cached"] is False
    assert answer["outline_source"] == "fallback · slotted"
    params = {p["name"]: p["default"] for p in answer["parameters"]}
    assert (params["thickness"], params["slot_width_a"], params["slot_width_b"]) == (3.0, 6.0, 5.5)
    assert answer["hole_counts"] == {"slots": 6, "shaped": 0}
    second = client.post("/api/runs/A_light/matching/adapter/slotted", json=_outline_body())
    assert second.json()["cached"] is True
    stl = client.post("/api/runs/A_light/model?match=adapter",
                      json={**_assembly_body("slotted"), "parameters": {}})
    assert stl.status_code == 200 and len(stl.content) > 84


def test_exact_as_measured_has_zero_interference():
    _searched()
    answer = client.post("/api/runs/A_light/matching/adapter/assembly", json=_assembly_body())
    assert answer.status_code == 200
    check = answer.json()
    assert check["verdict"] == "pass" and check["message"] == "All 6 screws pass"
    assert [(s["id"], s["overlap_mm3"]) for s in check["screws"]] == [
        ("A1", 0.0), ("A2", 0.0), ("A3", 0.0), ("A4", 0.0), ("B1", 0.0), ("B2", 0.0)]
    assert [p["label"] for p in check["plates"]] == ["original", "adapter (exact)", "stand-in plate"]
    assert check["skipped"] == []
    assert {g["key"]: g["default"] for g in check["groups"]} == {"5.50": "M5", "6.00": "M5"}
    plate = client.get(check["plates"][0]["stl"])
    assert plate.status_code == 200 and len(plate.content) > 84
    assert check["artifacts"]["A1"]["clashes"] == []
    report = json.loads((server.MATCHING_DIR / f"asm_{check['check_id']}" / "report.json").read_text(
        encoding="utf-8"))
    for screw in report["screws"]:  # every screw against every plate, joined or not
        assert sorted(screw["interference_mm3"]) == ["adapter", "mating", "original"]


def test_exact_with_error_blocks_every_screw():
    _searched()
    check = client.post("/api/runs/A_light/matching/adapter/assembly",
                        json=_assembly_body("exact", "with_error")).json()
    assert check["verdict"] == "blocked" and check["message"] == "6 of 6 screws blocked"
    assert all(s["verdict"] == "blocked" and s["overlap_mm3"] > 0 for s in check["screws"])
    assert check["artifacts"]["B2"]["clashes"] != []
    # Penetration depth from the clash solids: 0.64 mm shift minus the radial slack.
    depths = {s["id"]: s["depth_mm"] for s in check["screws"]}
    assert all(depths[f"A{i}"] == pytest.approx(0.14, abs=0.02) for i in (1, 2, 3, 4))
    assert all(depths[f"B{i}"] == pytest.approx(0.39, abs=0.02) for i in (1, 2))


def test_slotted_with_error_passes():
    _searched()
    client.post("/api/runs/A_light/matching/adapter/slotted", json=_outline_body())
    check = client.post("/api/runs/A_light/matching/adapter/assembly",
                        json=_assembly_body("slotted", "with_error")).json()
    assert check["verdict"] == "pass" and check["message"] == "All 6 screws pass"
    assert all(s["overlap_mm3"] == 0.0 for s in check["screws"])
    assert [p["label"] for p in check["plates"]] == ["original", "adapter (slotted)", "stand-in plate"]


def test_screw_overrides_and_skips():
    _searched()
    check = client.post("/api/runs/A_light/matching/adapter/assembly",
                        json=_assembly_body(screws={"6.00": "M4", "5.50": None})).json()
    assert [s["d"] for s in check["screws"]] == [4.0] * 4
    assert len(check["skipped"]) == 1 and "no metric screw fits" in check["skipped"][0]["message"]
    bad = client.post("/api/runs/A_light/matching/adapter/assembly", json=_assembly_body(screws={"6.00": "M12"}))
    assert bad.status_code == 400 and "unknown screw size" in bad.json()["detail"]


def test_assembly_validates_its_inputs():
    _searched()
    assert client.post("/api/runs/A_light/matching/adapter/assembly",
                       json=_assembly_body(error="maybe")).status_code == 400
    assert client.post("/api/runs/A_light/matching/adapter/assembly",
                       json=_assembly_body(style="oval")).status_code == 400
    assert client.post("/api/runs/no_such_run/matching/adapter/assembly",
                       json=_assembly_body()).status_code == 404
    assert client.get("/api/runs/A_light/matching/adapter/assembly/nope/plate_original.stl").status_code == 404
    check = client.post("/api/runs/A_light/matching/adapter/assembly", json=_assembly_body()).json()
    assert client.get(f"/api/runs/A_light/matching/adapter/assembly/{check['check_id']}/plate_original.stl").status_code == 200
    assert client.get(f"/api/runs/A_light/matching/adapter/assembly/{check['check_id']}/../../server.py").status_code == 404


def test_mating_plate_serves_the_stand_in_for_presets():
    _searched()
    answer = client.post("/api/runs/A_light/matching/adapter/mating/plate", json=_outline_body())
    assert answer.status_code == 200
    assert answer.json()["label"] == "stand-in plate" and answer.json()["thickness"] == 3.0
    stl = client.get(answer.json()["stl"])
    assert stl.status_code == 200 and len(stl.content) > 84


def test_assembly_works_in_demo_mode(monkeypatch):
    _searched()
    monkeypatch.setattr(server, "DEMO", True)
    check = client.post("/api/runs/A_light/matching/adapter/assembly", json=_assembly_body()).json()
    assert check["verdict"] == "pass" and check["plates"][-1]["label"] == "stand-in plate"


def test_check_draws_pattern_a_slots_in_slotted_mode_only():
    _searched()
    client.post("/api/runs/A_light/matching/adapter/slotted", json=_outline_body())
    exact = client.post("/api/runs/A_light/matching/adapter/check", json=_assembly_body("exact")).json()
    assert exact["holes_a"] is None
    check = client.post("/api/runs/A_light/matching/adapter/check", json=_assembly_body("slotted")).json()
    forms = check["holes_a"]
    assert len(forms) == 4
    for form in forms:  # the slotted rule: diameter + 2 x SHIFT_MM along pattern A's axis
        assert form["length"] == pytest.approx(6.0 + 2 * SHIFT_MM)
        assert form["width"] == pytest.approx(6.0) and form["angle"] == 0.0
    built = []  # every form sits on a slot of the built slotted adapter
    for hole in check["matching"]["holes"]:
        xs = [p[0] for p in hole["points"]]
        ys = [p[1] for p in hole["points"]]
        built.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    for form in forms:
        assert min(math.dist([form["x"], form["y"]], c) for c in built) == pytest.approx(0.0, abs=0.01)
