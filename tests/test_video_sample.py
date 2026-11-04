"""The run shown in the demo video, packed as a keyless sample (samples/live-20261104-220642-d6003c):
its recorded model outputs, labels, gallery order, ruler truth, and the recorded Muse Spark Open adapter
outline replayed without keys (same assembly verdicts as in the video). No test calls a model."""
import json
import urllib.parse

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import adapter_outline
from webapp import gallery, recorded_outline, replay, server

RUN = "live-20261104-220642-d6003c"
OLDER = "live-20261103-224610-c8b8df"
FOLDER = replay.SAMPLES_DIR / RUN
client = TestClient(server.app)
APPLY = {"X-Completion-Decision": urllib.parse.quote(json.dumps({"decision": "apply", "values": {}}))}
PRESET = {"holes": [{"x": -30.0, "y": 0.0, "d": 5.5}, {"x": 30.0, "y": 0.0, "d": 5.5}], "label": "2 × M5 · 60 mm"}

pytestmark = pytest.mark.skipif(not FOLDER.exists(), reason="needs the video-run sample")


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch, tmp_path):
    """As in the online demo: only samples/, no keys, a fresh matching cache, and no model ever reachable."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.setenv("BASETEN_API_KEY", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setattr(server, "MATCHING_DIR", tmp_path)

    def no_model(*args, **kwargs):
        raise AssertionError("a model was called")
    monkeypatch.setattr(adapter_outline, "search_adapter_outlines", no_model)
    monkeypatch.setattr(adapter_outline, "repair_adapter_outlines", no_model)
    replay.analysis.cache_clear()


def test_sample_keeps_the_recorded_outputs_and_not_the_decision():
    summary = json.loads((FOLDER / "5_summary_candidates_arcs_effort_medium.json").read_text(encoding="utf-8"))
    assert (summary["requested"], summary["compiled"], summary["within_deviation"]) == (5, 5, 0)
    assert summary["repair"]["passed"] and summary["repair"]["rounds"][0]["diagnosis"].startswith("cand_3, cand_4 and cand_5")
    assert summary["winner"]["iou"] == 0.9674 and summary["winner"]["parameter_count"] == 9
    completion = json.loads((FOLDER / "6_completion" / "completion.json").read_text(encoding="utf-8"))
    assert completion["valid"] and completion["check"]["added_volume_mm3"] == 253.5
    assert not (FOLDER / "6_completion" / "decision.json").exists()  # judges see the card undecided
    assert not (FOLDER / "6_completion" / "applied.py").exists()
    voice = json.loads((FOLDER / "7_adapter_recorded" / "voice.json").read_text(encoding="utf-8"))
    assert voice["transcript"] == "two metric five holes sixty millimeters apart"
    assert voice["parsed_pattern"]["holes"] == PRESET["holes"]
    outline = json.loads((FOLDER / "7_adapter_recorded" / "outline.json").read_text(encoding="utf-8"))
    assert outline["outline_source"] == "Muse Spark Open" and outline["winner"] == 1
    assert [c["ok"] for c in outline["candidates"]] == [True, True, True]
    usage = [json.loads(line) for line in (FOLDER / "usage.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {u["model"] for u in usage} == {"sam-3.1", "meta-models/muse-spark-open-1026", "muse-wonder-1.0",
                                          "muse-voice-transcribe-1.0"}


def test_photo_is_the_reviewed_one_without_exif():
    new, old = Image.open(FOLDER / "1_scene.jpg"), Image.open(replay.SAMPLES_DIR / OLDER / "1_scene.jpg")
    assert not dict(new.getexif())
    assert np.array_equal(np.asarray(new), np.asarray(old))  # the same edited BREAK1 photo, already reviewed


def test_labels_order_and_ruler_truth():
    assert client.get(f"/api/runs/{RUN}/info").json()["title"] == "the run in the video (Nov 4)"
    assert client.get(f"/api/runs/{OLDER}/info").json()["title"] == "recorded live run (Nov 3)"
    cards = gallery.gallery_runs()
    assert [c["name"] for c in cards[:2]] == [RUN, OLDER] and all(c["kind"] == "Synthetic" for c in cards[2:])
    truth = client.get(f"/api/runs/{RUN}/winner").json()["ground_truth"]
    assert truth["kind"] == "ruler" and [real for _, real in (truth["length"], truth["width"])] == [106.5, 96.0]


def test_recorded_outline_matches_only_the_recorded_inputs():
    meta = json.loads((FOLDER / "7_adapter_recorded" / "outline.json").read_text(encoding="utf-8"))
    args = (meta["holes_a"], meta["placement"]["holes_b"], meta["thickness"], meta["margin_default"])
    assert recorded_outline.find(FOLDER, *args) is not None
    assert recorded_outline.find(FOLDER, args[0], args[1], args[2], 5.77) is None  # another edge margin
    moved = [{**args[1][0], "x": args[1][0]["x"] + 1.0}, args[1][1]]
    assert recorded_outline.find(FOLDER, args[0], moved, args[2], args[3]) is None
    assert recorded_outline.find(replay.SAMPLES_DIR / "A_light", *args) is None  # no recording there


def _outline(headers):
    winner = client.get(f"/api/runs/{RUN}/winner", headers=headers).json()
    body = {"base": {p["name"]: p["default"] for p in winner["parameters"]}, "pattern": PRESET}
    answer = client.post(f"/api/runs/{RUN}/matching/adapter/outline", json=body, headers=headers)
    assert answer.status_code == 200, answer.text
    return body, answer.json()


def test_undecided_part_gets_the_fallback():
    # Before Apply the part's edge margin differs (5.77 vs the recorded 6.75), so the recording does not apply.
    _, answer = _outline({})
    assert answer["source"] == "Outline: fallback"


def test_applied_part_replays_the_recorded_outline_and_the_videos_verdicts():
    usage_before = (FOLDER / "usage.jsonl").read_bytes()
    body, answer = _outline(APPLY)
    assert answer["source"] == "Outline: Muse Spark Open · recorded"
    assert {p["name"]: p["default"] for p in answer["parameters"]} == {
        "length": 104.0, "width": 98.0, "margin": 6.75, "dia_a": 6.0, "dia_b": 5.5, "thickness": 3.0}
    assert client.post(f"/api/runs/{RUN}/matching/adapter/slotted", json=body, headers=APPLY).status_code == 200
    verdicts = {}
    for style in ("exact", "slotted"):
        check = client.post(f"/api/runs/{RUN}/matching/adapter/assembly", headers=APPLY,
                            json={**body, "hole_style": style, "error_case": "with_error"}).json()
        verdicts[style] = (check["message"], sorted({(s["depth_mm"], s["overlap_mm3"]) for s in check["screws"]}))
    assert verdicts["exact"][0] == "6 of 6 screws blocked"
    assert verdicts["exact"][1] == [(0.14, pytest.approx(1.02, abs=0.01)), (0.39, pytest.approx(4.66, abs=0.01))]
    assert verdicts["slotted"] == ("All 6 screws pass", [(0.0, 0)])
    assert (FOLDER / "usage.jsonl").read_bytes() == usage_before  # nothing was called or logged


def test_a_cached_keyless_fallback_gives_way_to_the_recording():
    body, first = _outline(APPLY)
    meta_path = next(p for p in server.MATCHING_DIR.glob("*.json") if not p.name.startswith(("slotted_", "asm_")))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["outline_source"] = "fallback"  # as left by an older keyless run before the recording shipped
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    _, again = _outline(APPLY)
    assert first["source"] == again["source"] == "Outline: Muse Spark Open · recorded"
