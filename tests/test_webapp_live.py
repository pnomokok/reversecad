"""Tests for the web app's live mode without calling any model.

The candidate step is fed the saved model answers of scene A as if they were arriving now.
Folders created here are removed at the end of each test.
"""
import io
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from run_candidate import run_candidate
from webapp import live, replay
from webapp.server import app

client = TestClient(app)
SOURCE = replay.RUNS_DIR / "A_light"
SOURCE_ROUND = SOURCE / "candidates_arcs_effort_medium"


@pytest.fixture
def cleanup():
    created = []
    yield created
    for name in created:
        shutil.rmtree(replay.RUNS_DIR / name, ignore_errors=True)


def test_upload_is_stored_upright_without_exif(cleanup):
    image = Image.new("RGB", (40, 20), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # EXIF orientation: rotate 90 degrees when displayed
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    response = client.post("/api/live/upload", files={"photo": ("phone.jpg", buffer.getvalue(), "image/jpeg")})
    assert response.status_code == 200
    name = response.json()["name"]
    cleanup.append(name)
    stored = Image.open(live.live_dir(name) / "1_scene.png")
    assert stored.size == (20, 40) and not stored.getexif()
    assert client.get(f"/api/runs/{name}/photo").status_code == 200


def test_non_image_upload_is_rejected():
    response = client.post("/api/live/upload", files={"photo": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400


@pytest.mark.skipif(not SOURCE_ROUND.exists(), reason="needs scene A's saved medium round")
def test_live_candidates_stream_offline(cleanup, monkeypatch):
    name = "live-20260101-000000-abcdef"
    cleanup.append(name)
    folder = replay.RUNS_DIR / name
    folder.mkdir()
    for file in ("1_scene.png", "2_sam_attempts.json", "3_measurements.json", "3_part_mask_topdown.png",
                 "3_mask_card.png", "3_mask_color.png"):
        shutil.copy(SOURCE / file, folder / file)

    def saved_answers(view, image, count, reasoning_effort=None, thickness=3.0):
        for index in range(1, count + 1):
            response = json.loads((SOURCE_ROUND / f"cand_{index}_response.json").read_text(encoding="utf-8"))
            yield "prompt", index, response

    monkeypatch.setattr(live, "iter_candidates", saved_answers)
    events = []
    live.candidates_job(name, 3, 3.0, run_candidate, events.append)

    candidates = [e for e in events if e["type"] == "candidate"]
    assert len(candidates) == 3 and all(e["status"] == "passed" for e in candidates)
    done = events[-1]
    assert done["type"] == "done" and done["winner"] in {1, 2, 3} and done["result_source"] == "candidate"
    # Saved like any run: screens 4-5 read it.
    assert replay.winner(name)["parameters"]
    assert Path(folder / f"5_summary_{live.ROUND}.json").exists()
