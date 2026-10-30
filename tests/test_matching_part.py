"""Matching parts: hole positions equal the original's, every sample builds, no model and no API key is used."""
import ast
import io
import json
import zipfile

import ezdxf
import pytest
from fastapi.testclient import TestClient

import build_worker
import matching_part
import partkit as pk
from candidates import check_code
from webapp import replay
from webapp.server import app

client = TestClient(app)
SAMPLES = ["A_light", "A_light_repair", "A_torn_fallback", "D_tab_broken"]
PROFILE = {
    "outline": [[0.0, 0.0], [80.0, 0.0], [80.0, 40.0], [0.0, 40.0]], "outline_arcs": [],
    "holes": [{"type": "circle", "center": [10.0, 10.0], "diameter": 6.0},
              {"type": "circle", "center": [70.0, 10.0], "diameter": 6.0},
              {"type": "circle", "center": [40.0, 30.0], "diameter": 9.0},
              {"type": "polyline", "points": [[30.0, 8.0], [50.0, 8.0], [50.0, 14.0], [30.0, 14.0]]}],
    "thickness": 3.0, "box": [0.0, 0.0, 80.0, 40.0]}


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    """As in the online demo: only samples/ and no API keys."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def _build(source, **overrides):
    namespace = {}
    exec(compile(source, "matching", "exec"), namespace)
    return build_worker.profile(namespace["build_part"](**overrides))


def _centers(profile):
    return sorted(tuple(round(c, 2) for c in matching_part._center(hole)) for hole in profile["holes"])


def _post(run, kind, parameters=None, base=None, path=""):
    return client.post(f"/api/runs/{run}/matching/{kind}{path}", json={"parameters": parameters or {}, "base": base or {}})


def test_generated_programs_pass_the_code_screen_and_import_no_model():
    for kind in matching_part.KINDS:
        source = matching_part.matching_source(PROFILE, kind)
        assert check_code(source) == []
        imports = {alias.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)
                   for alias in node.names}
        assert imports == {"partkit"}


def test_parameters_are_named_and_equal_holes_share_one():
    cover = {p["name"]: p for p in matching_part.slider_parameters(matching_part.matching_source(PROFILE, "cover"))}
    spacer = {p["name"]: p for p in matching_part.slider_parameters(matching_part.matching_source(PROFILE, "spacer"))}
    assert set(cover) == {"thickness", "hole_diameter_1", "hole_diameter_2"}
    assert set(spacer) == set(cover) | {"outline_offset"}
    assert cover["thickness"]["default"] == 3.0 and spacer["thickness"]["default"] == 1.0
    assert spacer["outline_offset"]["default"] == 0.0 and spacer["outline_offset"]["min"] < 0


def test_cover_has_the_same_outline_holes_and_its_own_thickness():
    built = _build(matching_part.matching_source(PROFILE, "cover"), thickness=7.5)
    assert built["thickness"] == 7.5 and built["box"] == PROFILE["box"]
    assert _centers(built) == _centers(PROFILE)
    assert sorted(h["diameter"] for h in built["holes"] if h["type"] == "circle") == [6.0, 6.0, 9.0]


def test_outline_offset_moves_the_outline_and_never_the_holes():
    source = matching_part.matching_source(PROFILE, "spacer")
    for offset in (-2.0, 3.0):
        built = _build(source, outline_offset=offset)
        assert built["box"] == pytest.approx([-offset, -offset, 80 + offset, 40 + offset], abs=0.01)
        assert matching_part.hole_alignment(PROFILE, built) == {"aligned": 4, "total": 4, "max_offset_mm": 0.0, "breakouts": 0}


def test_offset_works_on_a_curved_outline():
    # A plate with a round notch, as the profile gives it: many short edges around the arc.
    notched = pk.semicircle_notch(pk.plate(80, 40, 3), (0, 20), 8)
    profile = build_worker.profile(notched)
    assert len(profile["outline"]) > 10
    for offset in (-1.0, 2.0):
        box = _build(matching_part.matching_source(profile, "spacer"), outline_offset=offset)["box"]
        assert box[2] - box[0] == pytest.approx(80 + 2 * offset, abs=0.02)


def test_alignment_counts_what_is_really_there():
    moved = json.loads(json.dumps(PROFILE))
    moved["holes"][0]["center"] = [10.3, 10.4]
    assert matching_part.hole_alignment(PROFILE, moved) == {"aligned": 3, "total": 4, "max_offset_mm": 0.5, "breakouts": 0}
    missing = {**PROFILE, "holes": PROFILE["holes"][1:]}
    assert matching_part.hole_alignment(PROFILE, missing)["aligned"] == 3
    assert matching_part.hole_alignment({**PROFILE, "holes": []}, PROFILE) == {
        "aligned": 0, "total": 0, "max_offset_mm": None, "breakouts": 0}


def test_a_hole_opened_into_the_edge_is_aligned_and_reported_as_a_breakout():
    # At -9 mm the edges pass through all four holes, round and shaped; their centers have not moved.
    source = matching_part.matching_source(PROFILE, "spacer")
    built = _build(source, outline_offset=-9.0)
    assert built["holes"] == []
    assert matching_part.hole_alignment(PROFILE, built) == {"aligned": 4, "total": 4, "max_offset_mm": 0.0, "breakouts": 4}
    resized = _build(source, outline_offset=-9.0, hole_diameter_1=7.0)  # the arc's center, at any diameter
    assert matching_part.hole_alignment(PROFILE, resized)["breakouts"] == 4


def test_only_the_holes_that_break_through_are_counted_as_breakouts():
    built = _build(matching_part.matching_source(PROFILE, "spacer"), outline_offset=-6.5)
    # The new edges are at 6.5 and 33.5: the Ø9 hole reaches 34.5, the others stay inside (from 7 and 8).
    alignment = matching_part.hole_alignment(PROFILE, built)
    assert alignment["aligned"] == 4 and alignment["breakouts"] == 1 and len(built["holes"]) == 3


def test_a_hole_left_outside_the_outline_is_neither_aligned_nor_a_breakout():
    profile = {**PROFILE, "holes": [{"type": "circle", "center": [2.0, 2.0], "diameter": 2.0},
                                    {"type": "circle", "center": [40.0, 20.0], "diameter": 6.0}]}
    built = _build(matching_part.matching_source(profile, "spacer"), outline_offset=-5.0)
    assert matching_part.hole_alignment(profile, built) == {"aligned": 1, "total": 2, "max_offset_mm": 0.0, "breakouts": 0}


def test_an_unrelated_arc_on_the_outline_is_not_a_breakout():
    notched = build_worker.profile(pk.semicircle_notch(pk.plate(80, 40, 3), (-40, 0), 8))
    assert len(notched["outline_arcs"]) == 1
    hole = {"type": "circle", "center": [20.0, 0.0], "diameter": 6.0}
    assert matching_part.hole_alignment({**notched, "holes": [hole]}, notched)["breakouts"] == 0


def test_the_app_reports_a_breakout():
    alignment = _post("A_light", "spacer", {"outline_offset": -9.0}, path="/check").json()["alignment"]
    assert alignment == {"aligned": 4, "total": 4, "max_offset_mm": 0.0, "breakouts": 4}


@pytest.mark.parametrize("run", SAMPLES)
@pytest.mark.parametrize("kind", matching_part.KINDS)
def test_every_sample_builds_with_the_original_holes(run, kind):
    info = _post(run, kind)
    assert info.status_code == 200
    defaults = {p["name"]: p["default"] for p in info.json()["parameters"]}
    assert defaults["thickness"] == (3.0 if kind == "cover" else 1.0)

    stl = client.post(f"/api/runs/{run}/model?match={kind}", json={"parameters": {}, "base": {}})
    assert stl.status_code == 200 and len(stl.content) > 84
    built = json.loads(stl.headers["X-Model-Features"])
    assert round(built["box"][5] - built["box"][2], 2) == defaults["thickness"]

    check = _post(run, kind, path="/check").json()
    assert check["alignment"]["aligned"] == check["alignment"]["total"] > 0
    assert check["alignment"]["max_offset_mm"] <= 0.002 and check["alignment"]["breakouts"] == 0
    assert _centers(check["matching"]) == _centers(check["original"])
    assert check["matching"]["outline"] == check["original"]["outline"]
    assert sorted(h.get("diameter", 0) for h in check["matching"]["holes"]) == \
        sorted(h.get("diameter", 0) for h in check["original"]["holes"])


@pytest.mark.parametrize("run", SAMPLES)
def test_downloads_work_as_for_the_original(run):
    body = {"parameters": {"thickness": 2.0, "outline_offset": 1.0}, "base": {}}
    for format, start in (("stl", None), ("step", b"ISO-10303"), ("dxf", None), ("pdf", b"%PDF"),
                          ("py", f'"""{run}_spacer.py: Spacer / gasket of the original part.'.encode())):
        response = client.post(f"/api/runs/{run}/download?format={format}&match=spacer", json=body)
        assert response.status_code == 200, format
        assert f"reversecad_{run}_spacer" in response.headers["Content-Disposition"]
        assert start is None or response.content.startswith(start)
    drawing = client.post(f"/api/runs/{run}/drawing?match=spacer", json=body).json()
    assert drawing["name"] == f"{run}_spacer" and drawing["profile"]["thickness"] == 2.0
    dxf = client.post(f"/api/runs/{run}/download?format=dxf&match=spacer", json=body)
    space = ezdxf.read(io.StringIO(dxf.content.decode("utf-8"))).modelspace()
    assert len(space.query('*[layer=="CUT_INNER"]')) == len(drawing["profile"]["holes"])
    py = client.post(f"/api/runs/{run}/download?format=py&match=spacer", json=body).text
    assert "thickness=2.0" in py and "outline_offset=1.0" in py and check_code(py) == []
    archive = client.post(f"/api/runs/{run}/download?format=zip&match=spacer", json=body)
    assert len(zipfile.ZipFile(io.BytesIO(archive.content)).namelist()) == 5


def test_the_slider_values_of_the_original_carry_over():
    # A changed original (hole diameter 8): the cover gets that diameter at the same positions.
    original = replay.winner("A_light")["parameters"]
    assert "hole_diameter" in {p["name"] for p in original}
    base = {"hole_diameter": 8.0}
    info = _post("A_light", "cover", base=base).json()
    assert {p["name"]: p["default"] for p in info["parameters"]}["hole_diameter"] == 8.0
    alignment = _post("A_light", "cover", base=base, path="/check").json()["alignment"]
    assert alignment["aligned"] == alignment["total"] == 4


def test_a_hole_slider_stays_on_the_original_centers():
    check = _post("A_light", "spacer", {"hole_diameter": 4.0}, path="/check").json()
    assert check["alignment"]["aligned"] == 4
    assert {h["diameter"] for h in check["matching"]["holes"]} == {4.0}


def test_split_warning_names_the_computed_count():
    assert matching_part.split_warning(2) == "Gasket splits into 2 pieces at this offset — try a smaller offset."
    assert matching_part.split_warning(3).startswith("Gasket splits into 3 pieces")


def test_d_tab_broken_splits_at_minus_8():
    split = _post("D_tab_broken", "spacer", {"outline_offset": -8.0}, path="/check").json()
    assert split["pieces"] == 2
    assert split["warning"] == "Gasket splits into 2 pieces at this offset — try a smaller offset."
    whole = _post("D_tab_broken", "spacer", {"outline_offset": 0.0}, path="/check").json()
    assert whole["pieces"] == 1 and whole["warning"] is None


def test_split_gasket_downloads_and_drawing_are_refused():
    body = {"parameters": {"outline_offset": -8.0}, "base": {}}
    for format in ("stl", "step", "dxf", "py", "pdf", "zip"):
        answer = client.post(f"/api/runs/D_tab_broken/download?format={format}&match=spacer", json=body)
        assert answer.status_code == 422, format
        assert answer.json()["detail"] == matching_part.split_warning(2)
    assert client.post("/api/runs/D_tab_broken/drawing?match=spacer", json=body).status_code == 422
    whole = {"parameters": {"outline_offset": 0.0}, "base": {}}
    assert client.post("/api/runs/D_tab_broken/download?format=stl&match=spacer", json=whole).status_code == 200
    assert client.post("/api/runs/D_tab_broken/drawing?match=spacer", json=whole).status_code == 200


def test_split_refusal_is_the_same_in_the_demo(monkeypatch):
    monkeypatch.setattr("webapp.server.DEMO", True)
    body = {"parameters": {"outline_offset": -8.0}, "base": {}}
    answer = client.post("/api/runs/D_tab_broken/download?format=stl&match=spacer", json=body)
    assert answer.status_code == 422 and "splits into 2 pieces" in answer.json()["detail"]


def test_matching_docstring_uses_the_display_name():
    source = matching_part.matching_source(PROFILE, "cover", "A_light_cover.py")
    assert source.startswith('"""A_light_cover.py: Cover of the original part.')


def test_bad_requests_are_refused():
    assert _post("A_light", "lid").status_code == 400
    assert _post("A_light", "cover", {"length": 5.0}, path="/check").status_code == 400
    assert _post("A_light", "cover", base={"nonsense": 1.0}).status_code == 400
    assert _post("no_such_run", "cover").status_code == 404
    assert client.post("/api/runs/A_light/model?match=lid", json={}).status_code == 400
