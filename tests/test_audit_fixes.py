"""Fixes from the pre-submission audit (round 1): matching parts start from the original's values, completion
answers for samples stay in the browser, runs say what kind they are, and the .py export ships partkit.py.
No API calls (demo conditions: samples only, no keys)."""
import io
import json
import re
import subprocess
import sys
import urllib.parse
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp import gallery, replay, server
from webapp.server import app

client = TestClient(app)
APP_JS = Path("webapp/static/app.js").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    """As in the online demo and a fresh clone: only samples/ and no API keys."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def _function_body(name):
    start = APP_JS.index(f"async function {name}(")
    return APP_JS[start:APP_JS.index("\n}\n", start)]


# ---------- M1: every matching part starts from the original's values ----------

def test_new_matching_parts_take_the_saved_original_values_not_the_sliders():
    # While a matching part is shown, the sliders are its own (hole_diameter_a, outline_offset, ...);
    # reading them as the original's values made the next card or preset fail.
    assert "const originalValues = () => state.matching?.base ?? currentValues();" in APP_JS
    for name in ("showMatching", "runAdapter"):
        body = _function_body(name)
        assert "const base = originalValues();" in body and "const base = currentValues()" not in body


def _original_base():
    return {p["name"]: p["default"] for p in client.get("/api/runs/A_light/winner").json()["parameters"]}


def test_every_preset_in_sequence_equals_opening_it_fresh():
    base = _original_base()
    presets = client.get("/api/adapter/presets").json()["presets"]
    fresh = {}
    for index, preset in enumerate(presets):
        body = {"base": base, "pattern": preset, "outline": "fallback"}
        assert client.post("/api/runs/A_light/matching/adapter/place", json=body).status_code == 200
        answer = client.post("/api/runs/A_light/matching/adapter/outline", json=body)
        assert answer.status_code == 200
        fresh[index] = answer.json()["program"]
    # 1 -> 2 -> 3 -> 1 with the same original base gives the same programs as opening each fresh
    for index in (0, 1, 2, 0):
        body = {"base": base, "pattern": presets[index], "outline": "fallback"}
        assert client.post("/api/runs/A_light/matching/adapter/outline", json=body).json()["program"] == fresh[index]
    # the old bug: the adapter's own sliders sent as the original's values are refused
    adapter_values = {p["name"]: p["default"] for p in
                      client.post("/api/runs/A_light/matching/adapter/outline",
                                  json={"base": base, "pattern": presets[0], "outline": "fallback"}).json()["parameters"]}
    refused = client.post("/api/runs/A_light/matching/adapter/place", json={"base": adapter_values, "pattern": presets[1]})
    assert refused.status_code == 400 and "unknown or non-numeric parameter" in refused.json()["detail"]


def test_cover_and_spacer_from_the_original_base_equal_opening_them_fresh():
    base = _original_base()
    cover = client.post("/api/runs/A_light/matching/cover", json={"base": base}).json()
    spacer = client.post("/api/runs/A_light/matching/spacer", json={"base": base}).json()
    again = client.post("/api/runs/A_light/matching/cover", json={"base": base}).json()
    assert cover["program"] == again["program"] and cover["parameters"] == again["parameters"]
    assert spacer["program"] != cover["program"]


# ---------- M3: completion answers for samples are kept by the browser ----------

def _files(folder):
    return sorted((p.relative_to(folder).as_posix(), p.stat().st_size) for p in folder.rglob("*") if p.is_file())


def _header(answer):
    return {"X-Completion-Decision": urllib.parse.quote(json.dumps(answer))}


def test_sample_decisions_are_never_written_and_count_only_for_the_browser_that_sent_them():
    base = "/api/runs/D_tab_broken"
    folder = replay.run_dir("D_tab_broken")
    before = _files(folder)
    applied = client.post(f"{base}/completion/apply").json()
    assert applied["stored"] == "browser" and applied["decision"] == "apply"
    assert _files(folder) == before  # nothing written under samples/
    # another visitor (no header) still sees the undecided suggestion and the original result
    assert client.get(f"{base}/completion").json()["decision"] is None
    assert client.get(f"{base}/winner").json()["source"] != replay.COMPLETION_SOURCE
    # the browser that applied it sends its answer and gets the completed program
    mine = _header({"decision": "apply", "values": {}})
    assert client.get(f"{base}/winner", headers=mine).json()["source"] == replay.COMPLETION_SOURCE
    assert client.post(f"{base}/model", json={"parameters": {}}, headers=mine).status_code == 200
    ignored = client.post(f"{base}/completion/ignore").json()
    assert ignored["decision"] == "ignore" and _files(folder) == before
    assert client.get(f"{base}/completion", headers=_header({"decision": "ignore"})).json()["decision"] == "ignore"
    # a broken or foreign answer counts as none, never as a guess
    for bad in ({"decision": "apply", "values": {"length": 5}}, {"decision": "maybe"}, "x"):
        assert client.get(f"{base}/completion", headers=_header(bad)).json()["decision"] is None
    assert client.get(f"{base}/completion", headers={"X-Completion-Decision": "%%%"}).json()["decision"] is None
    assert _files(folder) == before


def test_own_runs_keep_writing_decision_json(monkeypatch, tmp_path):
    import shutil
    runs = tmp_path / "e2e"
    shutil.copytree(replay.SAMPLES_DIR / "D_tab_broken", runs / "D_tab_broken")
    monkeypatch.setattr(replay, "SOURCES", [runs, replay.SAMPLES_DIR])
    base = "/api/runs/D_tab_broken"
    answer = client.post(f"{base}/completion/ignore").json()
    assert answer["stored"] == "server" and answer["decision"] == "ignore"
    assert json.loads((runs / "D_tab_broken/6_completion/decision.json").read_text())["decision"] == "ignore"
    client.post(f"{base}/completion/undo")
    assert not (runs / "D_tab_broken/6_completion/decision.json").exists()


def test_show_suggestion_again_after_ignore():
    assert 'id="break-again"' in Path("webapp/static/index.html").read_text(encoding="utf-8")
    assert '$("break-again").classList.toggle("hidden", !(c && c.decision === "ignore"))' in APP_JS
    assert "localStorage" in APP_JS and "X-Completion-Decision" in APP_JS


# ---------- M4 / S1: the run says what it is ----------

def test_info_names_the_kind_from_the_same_source_as_the_gallery():
    for name in replay.list_samples():
        info = client.get(f"/api/runs/{name}/info").json()
        assert info["sample"] is True and info["kind"] == replay.run_kind(name)
        card = gallery.card(name)
        assert card["kind"].startswith(info["kind"])
    assert client.get("/api/runs/live-20261103-224610-c8b8df/info").json()["kind"] == "Real photo"
    assert client.get("/api/runs/A_light/info").json()["kind"] == "Synthetic"


def test_replay_is_labeled_and_its_stream_rows_do_not_show_the_wall_clock():
    assert "Replay of a recorded run" in Path("webapp/static/index.html").read_text(encoding="utf-8")
    assert '$("replay-chip").classList.toggle("hidden", !state.run || state.live);' in APP_JS
    assert "replay +" in APP_JS and 'state.live ? "Search finished" : "Replay finished"' in APP_JS


# ---------- M5: the .py export runs outside the repository ----------

def test_zip_ships_partkit_and_the_program_rebuilds_outside_the_repo(tmp_path):
    response = client.post("/api/runs/A_light/download?format=zip", json={"parameters": {}})
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "partkit.py" in archive.namelist()
    program = archive.read("reversecad_A_light.py").decode("utf-8")
    assert program.startswith("# Needs CadQuery and partkit.py (included in the zip).\n")
    single = client.post("/api/runs/A_light/download?format=py", json={"parameters": {}}).text
    assert single == program
    archive.extractall(tmp_path)
    # sys.path[0] = the unzipped folder, as when running "python reversecad_A_light.py" there
    code = ("import sys; sys.path.insert(0, '.'); import json, runpy; p = runpy.run_path('reversecad_A_light.py')['build_part']().val(); "
            "b = p.BoundingBox(); print(json.dumps([round(b.xlen, 3), round(b.ylen, 3), round(b.zlen, 3), round(p.Volume(), 1)]))")
    # -I: isolated, so nothing from the repository can be imported; only the unzipped folder
    run = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=300)
    assert run.returncode == 0, run.stderr[-500:]
    size = json.loads(run.stdout.strip().splitlines()[-1])
    assert size[:3] == [79.31, 40.26, 3.0]


# ---------- S3 / S11 / S12 ----------

def test_off_notes_keep_their_tab_class():
    assert 'filter((name) => name.startsWith("tab-"))' in APP_JS
    assert 'class="voice-card tab-parameters-only"' in Path("webapp/static/index.html").read_text(encoding="utf-8")


def test_stand_in_tag_without_a_measured_mating_photo():
    assert 'const tag = state.matching.mating ? "MATING PART" : "STAND-IN";' in APP_JS
    assert re.search(r'plate\.label === "stand-in plate" \? "STAND-IN" : "MATING PART"', APP_JS)


def test_stale_verdict_is_dimmed_while_the_check_reruns():
    assert "markVerdictChecking(true)" in _function_body("runAssemblyCheck")
    css = Path("webapp/static/app.css").read_text(encoding="utf-8")
    assert ".assembly-verdict.checking { opacity: 0.4; }" in css and 'content: "checking…"' in css
