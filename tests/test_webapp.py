"""Tests for the web app back end in replay mode (saved runs, no API calls)."""
import json

import pytest
from fastapi.testclient import TestClient

from webapp import replay, server
from webapp.server import app

client = TestClient(app)
needs_saved_run = pytest.mark.skipif("A_light" not in replay.list_runs(),
                                     reason="needs the saved run outputs/e2e/A_light (run_template_scenes.py)")


def test_page_and_styles_are_served():
    assert "ReverseCAD" in client.get("/").text
    tokens = client.get("/static/tokens.css").text
    assert "--color-accent" in tokens
    # Layout must not hard-code colors: every color lives in tokens.css.
    layout = client.get("/static/app.css").text
    assert "#" not in layout.replace("#steps", "")


def test_unknown_run_is_404():
    assert client.get("/api/runs/no_such_run/analysis").status_code == 404
    assert client.get("/api/runs/..%2F..%2Fdata/analysis").status_code == 404


def _events(body):
    """Parse a server-sent-events body into (event type, data) pairs."""
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


@needs_saved_run
def test_candidate_stream_replays_the_saved_round(monkeypatch):
    monkeypatch.setattr(server, "REPLAY_DELAY_S", 0)
    events = _events(client.get("/api/runs/A_light/candidates/stream").text)
    candidates = [data for kind, data in events if kind == "candidate"]
    kind, done = events[-1]
    assert kind == "done" and len(candidates) == done["candidate_count"]
    assert done["winner"] in [c["candidate"] for c in candidates if c["status"] == "passed"]
    png = client.get(candidates[0]["silhouette"])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


@pytest.mark.skipif("C" not in replay.list_runs(), reason="needs the saved run outputs/e2e/C")
def test_failed_candidate_has_a_reason_and_no_silhouette(monkeypatch):
    monkeypatch.setattr(server, "REPLAY_DELAY_S", 0)
    failed = [data for kind, data in _events(client.get("/api/runs/C/candidates/stream").text)
              if kind == "candidate" and data["status"] == "failed"]
    if not failed:
        pytest.skip("this saved round has no failed candidate")
    assert failed[0]["reasons"] and failed[0]["silhouette"] is None


@needs_saved_run
def test_saved_run_analysis():
    assert "A_light" in client.get("/api/runs").json()["runs"]
    assert client.get("/api/runs/A_light/photo").headers["content-type"] == "image/png"
    data = client.get("/api/runs/A_light/analysis").json()
    assert len(data["card_corners_px"]) == 4
    assert len(data["holes"]) == data["table"]["hole_count"] == 4
    assert abs(data["outline_mm"]["length"] - 80) < 1 and abs(data["outline_mm"]["width"] - 40) < 1
    assert data["click_px"] and len(data["outline_px"]) > 4
