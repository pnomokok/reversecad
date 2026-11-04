"""Fixes from the final audit before the demo video: the 3D view keeps the model inside the viewer, the
drawing's hole table lists centers, the keyless Capture screen says "Try an example", and matching parts
name a slot like the original. No API calls (samples only)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp import replay
from webapp.server import app

client = TestClient(app)
APP_JS = Path("webapp/static/app.js").read_text(encoding="utf-8")
VIEWER_JS = Path("webapp/static/viewer.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def samples_only(monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])


def _base(run):
    return {p["name"]: p["default"] for p in client.get(f"/api/runs/{run}/winner").json()["parameters"]}


def test_hole_table_lists_every_hole_center():
    # The drawing's profile: the rectangle and the slot of E_glossy_white, centered as designed (20, 20)
    # and (50, 20) within the measurement error; the table takes the middle of each hole's extent.
    data = client.post("/api/runs/E_glossy_white/drawing", json={"parameters": {}}).json()
    x0, y0 = data["profile"]["box"][:2]
    centers = sorted(
        ((min(q[0] for q in h["points"]) + max(q[0] for q in h["points"])) / 2 - x0,
         (min(q[1] for q in h["points"]) + max(q[1] for q in h["points"])) / 2 - y0)
        for h in data["profile"]["holes"])
    assert centers[0] == pytest.approx((20, 20), abs=0.5)
    assert centers[1] == pytest.approx((50, 20), abs=0.5)
    assert '[["HOLE", "CENTER X", "CENTER Y", "SIZE"], ...rows]' in APP_JS
    assert "fmt(mid(h, 0) - x0), fmt(mid(h, 1) - y0)" in APP_JS
    assert "fmt(span(h, 0)[0] - x0), fmt(span(h, 1)[0] - y0)" not in APP_JS


def test_keyless_capture_screen_does_not_offer_an_upload():
    assert '$("stage-empty").textContent = "Try an example.";' in APP_JS


@pytest.mark.parametrize("kind", ["cover", "spacer"])
def test_matching_parts_name_a_slot_like_the_original(kind):
    base = _base("E_glossy_white")
    client.post(f"/api/runs/E_glossy_white/matching/{kind}", json={"base": base})
    response = client.post(f"/api/runs/E_glossy_white/model?match={kind}", json={"base": base, "parameters": {}})
    assert response.status_code == 200, response.text
    kinds = json.loads(response.headers["X-Model-Features"])["hole_kinds"]
    assert kinds == {"round": 0, "slot": 1, "rectangular": 1, "shaped": 0}


def test_pan_and_zoom_keep_the_model_inside_the_viewer():
    # The label pan also bounds the model's projected box (part, ghosts, suggestion) by the viewer edges,
    # and a rebuild that keeps the view recomputes the pan for the new part.
    assert "const modelBox = part ? framedBox() : null;" in VIEWER_JS
    assert "right = Math.max(right, hi - (viewRect.width - 8));" in VIEWER_JS
    assert "if (left + right <= 0) break;" in VIEWER_JS
    assert "else if (!assembly) {  // same direction and frame; the pan is recomputed" in VIEWER_JS
