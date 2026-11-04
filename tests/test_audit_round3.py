"""Fixes from the pre-submission audit (round 3): gallery order and chips, hole counts by shape, label precision,
card-edge values, the front-view title, deep-link messages, the gasket split header and empty SVG paths.
No API calls (samples only)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp import gallery, replay
from webapp.server import app

client = TestClient(app)
APP_JS = Path("webapp/static/app.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def samples_only(monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])


def _features(run, body, match=None):
    response = client.post(f"/api/runs/{run}/model" + (f"?match={match}" if match else ""), json=body)
    assert response.status_code == 200, response.text
    return json.loads(response.headers["X-Model-Features"])


def test_gallery_shows_the_real_photo_first_with_two_short_chips():
    cards = gallery.gallery_runs()
    assert cards[0]["name"] == "live-20261103-224610-c8b8df"
    assert (cards[0]["kind"], cards[0]["recorded"]) == ("Real photo", True)
    assert all(c["kind"] == "Synthetic" and not c["recorded"] for c in cards[1:])
    assert '<span class="status-chip">Recorded run</span>' in Path("webapp/static/parts.js").read_text(encoding="utf-8")


def test_hole_counts_name_each_shape_from_the_built_model():
    assert _features("E_glossy_white", {"parameters": {}})["hole_kinds"] == {"round": 0, "slot": 1, "rectangular": 1, "shaped": 0}
    assert _features("A_light", {"parameters": {}})["hole_kinds"] == {"round": 4, "slot": 0, "rectangular": 0, "shaped": 0}
    assert '[kinds.round, "round hole"], [kinds.slot, "slot"], [kinds.rectangular, "rectangular hole"]' in APP_JS


def test_a_split_gasket_header_states_the_split():
    base = {p["name"]: p["default"] for p in client.get("/api/runs/D_tab_broken/winner").json()["parameters"]}
    spacer = client.post("/api/runs/D_tab_broken/matching/spacer", json={"base": base}).json()
    offset = next(p for p in spacer["parameters"] if p["name"] == "outline_offset")
    built = _features("D_tab_broken", {"base": base, "parameters": {"outline_offset": offset["min"]}}, match="spacer")
    assert built["solids"] == 2
    assert "<strong>Splits into ${features.solids} pieces</strong>" in APP_JS


def test_labels_and_card_edges_are_written_like_the_table():
    assert "return `${count}Ø${mean.toFixed(2)}`;" in APP_JS  # 2 decimals, as the measurement table
    assert APP_JS.count("edgeDifferences(a)") == 2  # footer and guided procedure, one formatter
    assert "Math.abs(d).toFixed(1)).join" not in APP_JS


def test_front_view_title_sits_right_of_the_thickness_line():
    assert '<text class="view-title" x="${X(x0)}" y="${fy - 4}">VIEW B · FRONT</text>' in APP_JS
    assert "const fl = X(x0) - 12;" in APP_JS  # the line runs left of the title's start


def test_deep_links_to_unknown_runs_and_rounds_say_so():
    assert 'Run not found: "${esc(run)}". <a href="/" class="inline-link">Try one of the examples</a>.' in APP_JS
    assert 'No saved round "${esc(state.round)}" for this run.' in APP_JS
    assert 'state.streamStopped ? `<span class="tag-bad">Stopped</span>`' in APP_JS
    assert client.get("/api/runs/A_light/candidates/stream?round=bogus").status_code == 404


def test_overlay_never_writes_an_empty_path():
    assert '(points.length ? `M${points.map(([x, y]) => `${x},${-y}`).join("L")}Z` : "")' in APP_JS
    assert '.filter(([, d]) => d).map(([kind, d]) => `<path class="${kind}" d="${d}"/>`)' in APP_JS
