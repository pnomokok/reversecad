"""Adapter API: presets are served without keys; free-text parsing needs Muse Spark Open."""
import pytest
from fastapi.testclient import TestClient

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
