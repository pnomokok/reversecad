"""Tests for the web app back end in replay mode (saved runs, no API calls)."""
import pytest
from fastapi.testclient import TestClient

from webapp import replay
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


@needs_saved_run
def test_saved_run_analysis():
    assert "A_light" in client.get("/api/runs").json()["runs"]
    assert client.get("/api/runs/A_light/photo").headers["content-type"] == "image/png"
    data = client.get("/api/runs/A_light/analysis").json()
    assert len(data["card_corners_px"]) == 4
    assert len(data["holes"]) == data["table"]["hole_count"] == 4
    assert abs(data["outline_mm"]["length"] - 80) < 1 and abs(data["outline_mm"]["width"] - 40) < 1
    assert data["click_px"] and len(data["outline_px"]) > 4
