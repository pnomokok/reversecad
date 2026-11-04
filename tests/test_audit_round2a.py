"""Fixes from the pre-submission audit (round 2a): the Adapter card always opens the adapter, a matching part's
sliders sit on its own tab, the round and the repair inputs are named in plain words, and one program name is
used everywhere. No API calls (demo conditions: samples only, no keys)."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repair_inputs import MAX_FAILED_SHOWN
from webapp import replay, server
from webapp.server import app

client = TestClient(app)
APP_JS = Path("webapp/static/app.js").read_text(encoding="utf-8")
APP_CSS = Path("webapp/static/app.css").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def demo_conditions(monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    monkeypatch.setattr(server, "REPLAY_DELAY_S", 0)
    monkeypatch.delenv("BASETEN_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)


def _function(name):
    start = APP_JS.index(f"function {name}(")
    return APP_JS[start:APP_JS.index("\n}\n", start)]


def _events(run):
    body = client.get(f"/api/runs/{run}/candidates/stream").text
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


# ---------- N1: the Adapter plate card opens the adapter on the first click ----------

def test_adapter_card_never_toggles_the_panel_closed():
    panel = _function("showAdapterPanel")
    assert 'classList.toggle("hidden")' not in panel and '$("adapter-panel").classList.remove("hidden")' in panel
    opener = _function("openAdapter")
    # a cover or spacer on screen gives way to the original first, as when the adapter is opened fresh
    assert 'state.matching.kind !== "adapter"' in opener and "showModel(state.matching.base)" in opener
    assert "openAdapter()" in APP_JS
    # the panel does not linger under a cover, a spacer or the original
    assert "closeAdapterPanel();" in _function("showModel") and "closeAdapterPanel();" in _function("showMatching")


# ---------- S2: a matching part's own sliders on the Matching part tab ----------

def test_matching_part_sliders_and_downloads_show_on_the_matching_tab():
    for part in ("edit-panel-head", "sliders", "exports-block"):
        assert f'.edit-panel.matching-mode[data-tab="matching"] .{part}' in APP_CSS
    # Parameters / step 3 mean the original while a matching part is shown: the step bar stays on 4 Match
    assert "if (state.matching) return showModel(state.matching.base);" in _function("goEdit")
    assert 'button.dataset.tab === "matching" ? setScreen("match") : goEdit()' in APP_JS


# ---------- S8 / S10: the round and the repair in plain words ----------

def test_rounds_are_named_in_plain_words():
    for run in replay.list_samples():
        done = _events(run)[-1]
        assert done["round_label"] == "Round 1 · medium effort", run
    assert 'state.done.round_label ? `<strong>${esc(state.done.round_label)}</strong>`' in APP_JS


@pytest.mark.parametrize("run, given, failed", [("live-20261103-224610-c8b8df", 3, 5), ("A_light_repair", 2, 2)])
def test_repair_card_says_how_many_failures_muse_wonder_was_given(run, given, failed):
    repaired = [e for e in _events(run) if e.get("label") == "R1"]
    assert len(repaired) == 1
    assert (repaired[0]["repair_given"], repaired[0]["failed_count"]) == (given, failed)
    assert given <= MAX_FAILED_SHOWN  # the same cap as repair_inputs.pick_failed


def test_runs_without_a_repair_say_nothing_about_one():
    assert not any("repair_given" in e for e in _events("A_light"))
    assert '` + ${repairs} repair${repairs > 1 ? "s" : ""}`' in APP_JS


# ---------- S14: one program name, the downloaded .py's ----------

def test_one_program_name_everywhere():
    assert 'const programFile = () => `reversecad_${state.run}${state.matching ? `_${state.matching.kind}` : ""}.py`;' in APP_JS
    assert APP_JS.count("Program ${programFile()}") == 4  # original, cover/spacer, adapter, adapter style switch
    assert "${data.program}" not in APP_JS  # export subbar and drawing title block use the same name
    name = client.post("/api/runs/A_light/download?format=py", json={"parameters": {}}).headers["Content-Disposition"]
    assert 'filename="reversecad_A_light.py"' in name


# ---------- S4 / S6 ----------

def test_dimension_line_follows_the_drawn_silhouette_and_actions_stay_in_view():
    assert "SILHOUETTE_PAD_PX = 20" in APP_JS and "np.pad(mask[ys.min()" in Path("webapp/replay.py").read_text(encoding="utf-8")
    assert "fitDimensionLine(card," in _function("winnerCard") and "fitDimensionLine(card," in _function("fallbackCard")
    assert ".candidate-card.winner.repaired {" in APP_CSS
    assert ".inspector-actions, .export-actions { position: sticky;" in APP_CSS
    assert 'class="export-actions"' in Path("webapp/static/index.html").read_text(encoding="utf-8")
