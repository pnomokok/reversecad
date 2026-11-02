"""Pattern B measured from a mating part's photo, without calling any model.

The pattern builder reads a saved measurement table (the sample scene with known holes);
the endpoints are fed staged live runs copied from it. Staged folders are removed at the end
of each test.
"""
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import mating_measure
from part_measurements import match_holes
from parts.template_parts import part_truth
from webapp import live, replay, server
from webapp.server import app

client = TestClient(app)
SAMPLE_TABLE = json.loads((replay.SAMPLES_DIR / "A_light" / "3_measurements.json").read_text(
    encoding="utf-8"))["table"]
# Scene E's saved measurements (synthetic plate, rectangular hole + slot, known truth).
E_TABLE = json.loads((Path(__file__).parent / "fixtures" / "E_measurements.json").read_text(
    encoding="utf-8"))["table"]


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    """Samples only and no API keys, as in the online demo (mating runs still stage locally)."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


@pytest.fixture
def cleanup():
    created = []
    yield created
    for name in created:
        shutil.rmtree(replay.RUNS_DIR / name, ignore_errors=True)


def _stage_mating(cleanup, measured=True):
    """A staged mating run from the sample scene (photo + measurements when measured)."""
    name = f"live-20260101-0000{len(cleanup):02d}-abcdef"
    cleanup.append(name)
    folder = replay.RUNS_DIR / name
    folder.mkdir(parents=True)
    shutil.copy(replay.SAMPLES_DIR / "A_light" / "1_scene.jpg", folder / "1_scene.png")
    if measured:
        shutil.copy(replay.SAMPLES_DIR / "A_light" / "3_measurements.json", folder / "3_measurements.json")
    return name, folder


def test_measured_pattern_matches_known_holes_within_tolerance():
    """Pattern B from saved scene E (rectangle + slot, symmetric layout): every true hole within the
    0.5 mm hole tolerance, in position and equal-area diameter."""
    result, error = mating_measure.pattern_from_table(E_TABLE)
    assert error is None
    assert result["summary"].endswith("measured from photo · SAM 3.1")
    assert result["pattern"]["label"].endswith("from photo")
    assert result["outline_mm"] == [E_TABLE["outline"]["length_mm"], E_TABLE["outline"]["width_mm"]]
    assert result["outline_polygon_mm"] == E_TABLE["outline"]["polygon_mm"]
    measured = [{"center_from_part_center_mm": [h["x"], h["y"]], "diameter_mm": h["d"]}
                for h in result["pattern"]["holes"]]
    assert len(measured) == 2
    for match in match_holes(measured, part_truth("E")["holes"]):
        assert match["measured"] is not None
        assert match["center_error_mm"] <= 0.5, match
        assert abs(match["diameter_error_mm"]) <= 0.5, match


def test_no_holes_is_refused_in_plain_words():
    result, error = mating_measure.pattern_from_table({"holes": [], "outline": {}})
    assert result is None
    assert error.startswith("No holes were found")


def test_unusable_measured_holes_are_refused_not_guessed():
    holes = [{"center_from_part_center_mm": [i * 10.0, 0.0], "diameter_mm": 6.0} for i in range(13)]
    result, error = mating_measure.pattern_from_table({"holes": holes, "outline": {}})
    assert result is None
    assert "can't be used as a hole pattern" in error


def test_mating_upload_stores_a_live_run(cleanup, tmp_path):
    photo = tmp_path / "mating.png"
    Image.new("RGB", (30, 20), "gray").save(photo)
    response = client.post("/api/runs/A_light/matching/adapter/mating/upload",
                           files={"photo": ("mating.png", photo.read_bytes(), "image/png")})
    assert response.status_code == 200
    name = response.json()["name"]
    cleanup.append(name)
    assert (live.live_dir(name) / "1_scene.png").exists()
    assert client.post("/api/runs/no_such_run/matching/adapter/mating/upload",
                       files={"photo": ("m.png", photo.read_bytes(), "image/png")}).status_code == 404


def test_pattern_endpoint_offline(cleanup):
    name, folder = _stage_mating(cleanup)
    answer = client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                         json={"mating": name, "thickness": 4.0})
    assert answer.status_code == 200
    body = answer.json()
    assert body["summary"].endswith("measured from photo · SAM 3.1")
    assert len(body["pattern"]["holes"]) == 4 and body["mating"] == name
    stored = json.loads((folder / "4_mating.json").read_text(encoding="utf-8"))
    assert stored["thickness_mm"] == 4.0 and stored["thickness_source"] == "entered"
    assert stored["outline_polygon_mm"] == SAMPLE_TABLE["outline"]["polygon_mm"]
    assert stored["main_run"] == "A_light" and stored["pattern"] == body["pattern"]
    assert client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                       json={"mating": name, "thickness": 0}).status_code == 400
    assert client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                       json={"mating": name, "thickness": "thick"}).status_code == 400


def test_pattern_endpoint_refuses_plainly(cleanup):
    staged, _ = _stage_mating(cleanup, measured=False)
    missing = client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                          json={"mating": staged, "thickness": 3.0})
    assert missing.status_code == 422 and "not been measured" in missing.json()["detail"]
    unknown = client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                          json={"mating": "live-20260101-000000-000000", "thickness": 3.0})
    assert unknown.status_code == 404 and "no mating photo run" in unknown.json()["detail"]
    name, _ = _stage_mating(cleanup)
    assert client.post("/api/runs/no_such_run/matching/adapter/mating/pattern",
                       json={"mating": name, "thickness": 3.0}).status_code == 404


def test_outline_links_the_mating_run(cleanup):
    for path in server.MATCHING_DIR.glob("*"):
        if path.is_file():
            path.unlink()
    name, _ = _stage_mating(cleanup)
    pattern = client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                          json={"mating": name, "thickness": 3.0}).json()["pattern"]
    body = {"base": {}, "pattern": pattern, "outline": "fallback", "mating": name}
    answer = client.post("/api/runs/A_light/matching/adapter/outline", json=body)
    assert answer.status_code == 200
    assert answer.json()["mating"] == {"run": name}
    check = client.post("/api/runs/A_light/matching/adapter/check", json={**body, "parameters": {}})
    assert check.status_code == 200 and check.json()["label_b"].endswith("from photo")
    bad = client.post("/api/runs/A_light/matching/adapter/outline",
                      json={**body, "mating": "live-20260101-000000-000000"})
    assert bad.status_code == 404 and "no mating photo run" in bad.json()["detail"]


def test_demo_mode_closes_photo_and_the_page_says_why(monkeypatch):
    monkeypatch.setattr(server, "DEMO", True)
    assert client.post("/api/runs/A_light/matching/adapter/mating/upload").status_code == 403
    response = client.post("/api/runs/A_light/matching/adapter/mating/pattern",
                           json={"mating": "live-20260101-000000-abcdef", "thickness": 3.0})
    assert response.status_code == 403 and "online demo" in response.json()["detail"]
    static = server.STATIC
    assert "From a photo" in (static / "index.html").read_text(encoding="utf-8")
    assert 'offNote($("mating-row")' in (static / "app.js").read_text(encoding="utf-8")
