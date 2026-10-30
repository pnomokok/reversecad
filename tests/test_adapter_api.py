"""Adapter API: presets are served without keys; free-text parsing needs Muse Spark Open."""
import pytest
from fastapi.testclient import TestClient

import adapter_outline
import adapter_pattern
from webapp import replay, server
from webapp.server import app

client = TestClient(app)
PATTERN = {"holes": [{"x": -30.0, "y": 0.0, "d": 5.5}, {"x": 30.0, "y": 0.0, "d": 5.5}], "label": "2 x M5"}


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    """As in the online demo: only samples/ and no API keys."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def test_presets_need_no_keys():
    answer = client.get("/api/adapter/presets").json()
    assert [p["label"] for p in answer["presets"]] == ["2 × M5 · 60 mm", "4 × M4 · 40 × 40 mm", "4 × M3 · 30 × 30 mm"]
    for preset in answer["presets"]:
        assert adapter_pattern.validate_pattern(preset)[1] is None


def test_parse_needs_a_key_and_a_run(monkeypatch):
    assert client.post("/api/runs/A_light/matching/adapter/parse", json={"text": "2 x M5"}).status_code == 503
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    assert client.post("/api/runs/no_such_run/matching/adapter/parse", json={"text": "2 x M5"}).status_code == 404
    assert client.post("/api/runs/A_light/matching/adapter/parse", json={"text": "  "}).status_code == 400


def test_parse_returns_the_validated_pattern(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    monkeypatch.setattr(adapter_pattern, "interpret_pattern",
                        lambda text, folder: {"pattern": PATTERN, "summary": "2 holes · Ø5.5 · 60 mm apart"})
    answer = client.post("/api/runs/A_light/matching/adapter/parse", json={"text": "2 x M5, 60 apart"})
    assert answer.status_code == 200 and answer.json()["summary"] == "2 holes · Ø5.5 · 60 mm apart"


def test_unreadable_text_is_422_with_a_message_not_a_guess(monkeypatch):
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    def fail(text, folder):
        raise RuntimeError("no hole pattern in that text")
    monkeypatch.setattr(adapter_pattern, "interpret_pattern", fail)
    answer = client.post("/api/runs/A_light/matching/adapter/parse", json={"text": "make it prettier"})
    assert answer.status_code == 422 and "pattern" in answer.json()["detail"]


def test_demo_mode_closes_parsing_but_keeps_presets(monkeypatch):
    monkeypatch.setattr(server, "DEMO", True)
    assert client.get("/api/adapter/presets").status_code == 200
    response = client.post("/api/runs/A_light/matching/adapter/parse", json={"text": "2 x M5"})
    assert response.status_code == 403 and "online demo" in response.json()["detail"]


def test_place_puts_a_preset_on_a_light():
    answer = client.post("/api/runs/A_light/matching/adapter/place",
                         json={"base": {}, "pattern": adapter_pattern.PRESETS[0]})
    assert answer.status_code == 200
    placed = answer.json()["placement"]
    assert placed["candidate"] == "centred" and len(placed["holes_b"]) == 2
    assert placed["walls"]["min"] >= 2.0


def test_place_reports_overlap_without_an_outline():
    thin = {"holes": [{"x": -3.0, "y": 0.0, "d": 5.5}, {"x": 3.0, "y": 0.0, "d": 5.5}], "label": "thin"}
    answer = client.post("/api/runs/A_light/matching/adapter/place", json={"base": {}, "pattern": thin})
    assert answer.status_code == 422 and answer.json()["detail"] == "Patterns overlap — can't place pattern B"


def test_place_validates_its_inputs():
    assert client.post("/api/runs/A_light/matching/adapter/place",
                       json={"base": {}, "pattern": {"holes": []}}).status_code == 422
    assert client.post("/api/runs/A_light/matching/adapter/place",
                       json={"base": {"nonsense": 1.0}, "pattern": adapter_pattern.PRESETS[0]}).status_code == 400
    assert client.post("/api/runs/no_such_run/matching/adapter/place",
                       json={"base": {}, "pattern": adapter_pattern.PRESETS[0]}).status_code == 404


def _outline_body(preset=0, **overrides):
    body = {"base": {}, "pattern": adapter_pattern.PRESETS[preset], "outline": "fallback"}
    body.update(overrides)
    return body


def _clear_matching_cache():
    """Adapter programs are cached by inputs across runs; fresh-path tests start without them."""
    for path in server.MATCHING_DIR.glob("*"):
        if path.is_file():
            path.unlink()


def test_outline_fallback_needs_no_keys_and_is_cached():
    _clear_matching_cache()
    first = client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body())
    assert first.status_code == 200
    answer = first.json()
    assert answer["outline_source"] == "fallback" and answer["cached"] is False
    assert answer["source"] == "Outline: fallback" and answer["title"] == "Adapter plate"
    assert answer["placement"]["candidate"] == "centred" and answer["winner"] is None
    params = {p["name"]: p["default"] for p in answer["parameters"]}
    assert (params["thickness"], params["hole_diameter_a"], params["hole_diameter_b"]) == (3.0, 6.0, 5.5)
    second = client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body())
    assert second.json()["cached"] is True and second.json()["program"] == answer["program"]


def test_outline_auto_falls_back_without_keys(monkeypatch):
    _clear_matching_cache()

    def fail(*args, **kwargs):
        raise AssertionError("no search without keys")
    monkeypatch.setattr(adapter_outline, "search_adapter_outlines", fail)
    answer = client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body(1, outline="auto"))
    assert answer.status_code == 200 and answer.json()["outline_source"] == "fallback"


def test_outline_uses_the_search_winner_with_keys(monkeypatch, tmp_path):
    _clear_matching_cache()
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    program = tmp_path / "winner.py"
    program.write_text(adapter_outline.fallback_source(
        [{"type": "circle", "center": [0.0, 0.0], "diameter": 6.0}], [{"x": 20.0, "y": 0.0, "d": 5.5}],
        3.0, "pair"), encoding="utf-8")
    rows = [{"candidate": 1, "style": "fewest_parameters", "file": str(program), "ok": True, "reasons": [],
             "matched": "2/2", "min_margin_mm": 2.0, "parameter_count": 3}]
    monkeypatch.setattr(adapter_outline, "search_adapter_outlines", lambda *a, **k: rows)
    answer = client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body(2, outline="auto"))
    assert answer.status_code == 200
    assert answer.json()["outline_source"] == "Muse Spark Open" and answer.json()["winner"] == 1
    assert answer.json()["candidates"] == rows


def test_check_reports_alignment_pattern_b_and_margins():
    client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body())
    answer = client.post("/api/runs/A_light/matching/adapter/check", json={**_outline_body(), "parameters": {}})
    assert answer.status_code == 200
    check = answer.json()
    assert check["alignment"] == {"aligned": 4, "total": 4, "max_offset_mm": 0.0, "breakouts": 0}
    assert len(check["holes_b"]) == 2 and check["label_b"] == "2 × M5 · 60 mm"
    assert check["min_margin_mm"] == 2.0 and check["outline_source"] == "fallback"


def test_model_and_drawing_work_for_the_adapter():
    client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body())
    stl = client.post("/api/runs/A_light/model?match=adapter", json={**_outline_body(), "parameters": {}})
    assert stl.status_code == 200 and len(stl.content) > 84
    drawing = client.post("/api/runs/A_light/drawing?match=adapter", json={**_outline_body(), "parameters": {}})
    assert drawing.json()["source"] == "Outline: fallback"


def _failing_search(*args, **kwargs):
    return [{"candidate": 1, "style": "fewest_parameters", "file": "/nonexistent.py", "ok": False,
             "reasons": ["pattern A hole 1: built 1.00 mm off"], "matched": "5/6", "min_margin_mm": 2.0,
             "parameter_count": 4}]


def test_outline_repairs_when_search_fails(monkeypatch, tmp_path):
    _clear_matching_cache()
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    monkeypatch.setenv("MODEL_API_KEY", "fake")
    monkeypatch.setattr(adapter_outline, "search_adapter_outlines", _failing_search)
    program = tmp_path / "repaired.py"
    program.write_text(adapter_outline.fallback_source(
        [{"type": "circle", "center": [0.0, 0.0], "diameter": 6.0}], [{"x": 20.0, "y": 0.0, "d": 5.5}],
        3.0, "pair"), encoding="utf-8")
    repaired = {"candidate": 101, "label": "R1", "style": "repair", "file": str(program), "ok": True, "reasons": [],
                "matched": "2/2", "min_margin_mm": 2.0, "parameter_count": 3, "diagnosis": "moved it back"}
    monkeypatch.setattr(adapter_outline, "repair_adapter_outlines",
                        lambda *a, **k: {"passed": True, "rows": [repaired], "result": repaired, "rounds": []})
    answer = client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body(0, outline="auto"))
    assert answer.status_code == 200
    assert answer.json()["outline_source"] == "Muse Wonder repair" and answer.json()["winner"] == 101
    assert len(answer.json()["candidates"]) == 2


def test_outline_falls_back_when_repair_fails(monkeypatch):
    _clear_matching_cache()
    monkeypatch.setenv("BASETEN_API_KEY", "fake")
    monkeypatch.setenv("MODEL_API_KEY", "fake")
    monkeypatch.setattr(adapter_outline, "search_adapter_outlines", _failing_search)
    failed = {"candidate": 101, "label": "R1", "style": "repair", "file": "/nonexistent.py",
              "error": "request failed", "diagnosis": None}
    monkeypatch.setattr(adapter_outline, "repair_adapter_outlines",
                        lambda *a, **k: {"passed": False, "rows": [failed], "result": None, "rounds": []})
    answer = client.post("/api/runs/A_light/matching/adapter/outline",
                         json=_outline_body(1, outline="auto", base={"thickness": 4.0}))
    assert answer.status_code == 200 and answer.json()["outline_source"] == "fallback"
    assert len(answer.json()["candidates"]) == 2


@pytest.mark.parametrize("preset", [0, 1, 2])
def test_adapter_end_to_end_with_the_fallback_outline(preset):
    """Each preset on A_light without any model: place, outline, check, every download."""
    body = _outline_body(preset)
    outline = client.post("/api/runs/A_light/matching/adapter/outline", json=body)
    assert outline.status_code == 200
    assert outline.json()["outline_source"] == "fallback"
    assert outline.json()["placement"]["candidate"] == "centred"

    holes_b = len(adapter_pattern.PRESETS[preset]["holes"])
    check = client.post("/api/runs/A_light/matching/adapter/check", json={**body, "parameters": {}}).json()
    assert check["alignment"] == {"aligned": 4, "total": 4, "max_offset_mm": 0.0, "breakouts": 0}
    assert len(check["holes_b"]) == holes_b and check["label_b"] == adapter_pattern.PRESETS[preset]["label"]
    assert check["min_margin_mm"] >= 2.0
    assert len(check["matching"]["holes"]) == 4 + holes_b

    stl = client.post("/api/runs/A_light/model?match=adapter", json={**body, "parameters": {}})
    assert stl.status_code == 200 and len(stl.content) > 84
    for format, start in (("stl", None), ("step", b"ISO-10303"), ("dxf", None), ("pdf", b"%PDF"),
                          ("py", b'"""Adapter plate')):
        response = client.post(f"/api/runs/A_light/download?format={format}&match=adapter",
                               json={**body, "parameters": {}})
        assert response.status_code == 200, format
        assert "reversecad_A_light_adapter" in response.headers["Content-Disposition"]
        assert start is None or response.content.startswith(start)
    drawing = client.post("/api/runs/A_light/drawing?match=adapter", json={**body, "parameters": {}}).json()
    assert drawing["name"] == "A_light_adapter" and drawing["source"] == "Outline: fallback"
    assert len(drawing["profile"]["holes"]) == 4 + holes_b and drawing["profile"]["thickness"] == 3.0


def test_adapter_validates_its_inputs():
    assert client.post("/api/runs/A_light/matching/adapter/outline",
                       json=_outline_body(outline="hexagon")).status_code == 400
    assert client.post("/api/runs/A_light/matching/adapter/outline",
                       json=_outline_body(pattern={"holes": []})).status_code == 422
    fresh = {"base": {}, "pattern": {"holes": [{"x": 0.0, "y": 0.0, "d": 6.6}], "label": "single M6"},
             "outline": "fallback", "parameters": {}}
    assert client.post("/api/runs/A_light/model?match=adapter", json=fresh).status_code == 404
    client.post("/api/runs/A_light/matching/adapter/outline", json=_outline_body())  # cache may be cleared
    assert client.post("/api/runs/A_light/matching/adapter/check",
                       json={**_outline_body(), "parameters": {"length": 5.0}}).status_code == 400
