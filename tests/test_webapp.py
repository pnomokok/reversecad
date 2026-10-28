"""Tests for the web app back end in replay mode (saved runs, no API calls)."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from candidates import check_code
from design_intent import parameters
from run_candidate import run_candidate
from webapp import replay, server
from webapp.server import app

client = TestClient(app)
needs_saved_run = pytest.mark.skipif("A_light" not in replay.list_runs(),
                                     reason="needs the saved run outputs/e2e/A_light (run_template_scenes.py)")


def test_page_and_styles_are_served():
    assert "ReverseCAD" in client.get("/").text
    tokens = client.get("/static/tokens.css").text
    assert "--color-selected" in tokens
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
    stream = client.get("/api/runs/C/candidates/stream?round=candidates_intent")  # a round with 2 failures
    if stream.status_code == 404:
        pytest.skip("this run has no saved candidates_intent round")
    failed = [data for kind, data in _events(stream.text) if kind == "candidate" and data["status"] == "failed"]
    assert failed and failed[0]["silhouette"] is None
    assert failed[0]["reasons"][0].startswith("no python code block")  # the technical text, for hovering
    assert failed[0]["plain_reasons"][0] == "ran out of reasoning budget, no code returned"


def test_plain_reasons():
    assert replay.plain_reason("no python code block (finish=stop, 900 output tokens)") == "the answer contained no code"
    assert replay.plain_reason("ValueError: Null TopoDS_Shape object") == "the program crashed while building the part"
    assert replay.plain_reason("hole 2 diameter: off by 0.8 mm (limit 0.5)") == "hole 2 diameter is off by 0.8 mm (limit 0.5)"


@needs_saved_run
def test_fit_and_ground_truth_are_separate(monkeypatch):
    monkeypatch.setattr(server, "REPLAY_DELAY_S", 0)
    winner = client.get("/api/runs/A_light/winner").json()
    assert 0 <= winner["fit_mm"] < 0.5  # follows the measurements closely
    truth = winner["ground_truth"]  # A_light shows template part A: 80 × 40 mm, four Ø6 holes
    assert [real for _, real in (truth["length"], truth["width"])] == [80, 40]
    assert abs(truth["length"][0] - 80) < 0.05 * 80 and all(abs(m - 6) < 0.3 for m, _ in truth["holes"])
    assert replay.ground_truth_error("live-anything", {"outline_mm": [1, 1]}) is None  # real photos: unknown


def _stl_x_extent(data):
    """Length along X of an STL (ASCII or binary)."""
    if data[:5] == b"solid" and b"facet" in data[:1000]:
        xs = [float(line.split()[1]) for line in data.decode().splitlines() if line.strip().startswith("vertex")]
    else:
        triangles = np.frombuffer(data[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]))
        xs = triangles["v"][:, :, 0].ravel()
    return max(xs) - min(xs)


@needs_saved_run
def test_result_model_builds_and_follows_a_slider():
    info = client.get("/api/runs/A_light/winner").json()
    names = {p["name"]: p["default"] for p in info["parameters"]}
    assert info["source"] == "candidate" and names
    default = client.post("/api/runs/A_light/model", json={"parameters": {}})
    assert default.status_code == 200
    length = max(names, key=names.get)  # the largest default is the plate length (80)
    longer = client.post("/api/runs/A_light/model", json={"parameters": {length: names[length] + 10}})
    assert _stl_x_extent(longer.content) - _stl_x_extent(default.content) == pytest.approx(10, abs=0.5)
    assert client.post("/api/runs/A_light/model", json={"parameters": {"__import__": 1}}).status_code == 400


@needs_saved_run
def test_downloads(tmp_path):
    names = {p["name"]: p["default"] for p in client.get("/api/runs/A_light/winner").json()["parameters"]}
    length = max(names, key=names.get)
    values = {"parameters": {length: names[length] + 10}}

    step = client.post("/api/runs/A_light/download?format=step", json=values)
    assert step.status_code == 200 and step.content.startswith(b"ISO-10303-21")
    assert 'filename="reversecad_A_light.step"' in step.headers["content-disposition"]

    program = client.post("/api/runs/A_light/download?format=py", json=values).text
    assert check_code(program) == []
    assert dict(parameters(program))[length] == round(names[length] + 10, 4)  # slider value is the new default
    path = tmp_path / "downloaded.py"
    path.write_text(program, encoding="utf-8")
    mask, error = run_candidate(path, 0.1)  # the downloaded program builds the longer part by itself
    assert error is None
    assert (mask.any(axis=0).sum() * 0.1) == pytest.approx(names[length] + 10, abs=0.5)

    assert client.post("/api/runs/A_light/download?format=dwg", json=values).status_code == 400


@pytest.mark.skipif(not (replay.SAMPLES_DIR / "A_light").exists(), reason="needs samples/A_light")
def test_sample_run_replays_like_a_fresh_clone(monkeypatch):
    """Only samples/ visible (outputs/ is git-ignored, so a fresh clone has nothing else)."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.setattr(server, "REPLAY_DELAY_S", 0)
    replay.analysis.cache_clear()
    try:
        assert client.get("/api/runs").json()["runs"] == ["A_light"]
        assert client.get("/api/runs/A_light/photo").headers["content-type"] == "image/jpeg"
        assert client.get("/api/runs/A_light/analysis").json()["table"]["hole_count"] == 4
        events = _events(client.get("/api/runs/A_light/candidates/stream").text)
        assert events[-1][0] == "done" and events[-1][1]["winner"]
        assert client.get(events[0][1]["silhouette"]).content[:4] == b"\x89PNG"
        assert client.post("/api/runs/A_light/model", json={"parameters": {}}).status_code == 200
        assert client.post("/api/runs/A_light/download?format=step", json={"parameters": {}}).status_code == 200
    finally:
        replay.analysis.cache_clear()


@needs_saved_run
def test_saved_run_analysis():
    assert "A_light" in client.get("/api/runs").json()["runs"]
    assert client.get("/api/runs/A_light/photo").headers["content-type"] == "image/png"
    data = client.get("/api/runs/A_light/analysis").json()
    assert len(data["card_corners_px"]) == 4
    assert len(data["holes"]) == data["table"]["hole_count"] == 4
    assert abs(data["outline_mm"]["length"] - 80) < 1 and abs(data["outline_mm"]["width"] - 40) < 1
    assert data["click_px"] and len(data["outline_px"]) > 4
