"""Voice editing answers are checked before they are shown; the online demo turns off what needs API keys."""
from fastapi.testclient import TestClient

from voice_edit import parse_answer
from webapp import server

client = TestClient(server.app)
PARAMETERS = {"length": 79.31, "width": 40.26, "thickness": 3.0, "hole_diameter": 6.0, "edge_margin": 8.0}


def test_only_real_changes_of_known_parameters_are_kept():
    answer = parse_answer('{"changes": [{"name": "hole_diameter", "value": 8.0}, {"name": "colour", "value": 1},'
                          ' {"name": "length", "value": -5}, {"name": "width", "value": 40.26}], "note": "ok"}', PARAMETERS)
    assert answer["changes"] == [{"name": "hole_diameter", "from": 6.0, "to": 8.0}]
    assert "colour" in answer["note"] and "length" in answer["note"]  # said what was left out


def test_an_answer_that_is_not_json_changes_nothing():
    assert parse_answer("I am not sure what you mean.", PARAMETERS)["changes"] == []
    assert parse_answer('```json\n{"changes": [], "note": "No parameter controls color."}\n```', PARAMETERS) == {
        "changes": [], "note": "No parameter controls color."}


def test_demo_mode_closes_what_needs_keys(monkeypatch):
    monkeypatch.setattr(server, "DEMO", True)
    assert client.get("/api/config").json() == {"demo": True, "live": False, "voice": False}
    assert client.post("/api/live/upload").status_code == 403
    assert client.get("/api/live/live-20260101-000000-abcdef/measure/stream?x=1&y=1").status_code == 403
    response = client.post("/api/runs/A_light/voice/interpret", json={"command": "x", "parameters": {}})
    assert response.status_code == 403 and "online demo" in response.json()["detail"]
