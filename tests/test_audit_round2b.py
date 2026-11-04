"""Fixes from the pre-submission audit (round 2b): Matching tab order, 3D labels clear of the suggestion,
which value each dimension is, grammar, readable sample names and the logo. No API calls."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp import gallery, replay
from webapp.server import app

client = TestClient(app)
STATIC = Path("webapp/static")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
APP_CSS = (STATIC / "app.css").read_text(encoding="utf-8")
VIEWER = (STATIC / "viewer.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def samples_only(monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])


def test_matching_tab_order_puts_the_assembly_check_before_the_sliders():
    order = {name: int(n) for name, n in re.findall(r"\.edit-panel\.matching-mode \.([a-z-]+) \{ order: (\d+); \}", APP_CSS)}
    assert order["matching-block"] < order["assembly-block"] < order["edit-panel-head"] < order["sliders"] < order["exports-block"]


def test_3d_labels_keep_clear_of_the_suggestion_and_inside_the_view():
    assert "const s = suggestionBox;" in VIEWER and "[0, -(gap + below), 0]" in VIEWER  # dimension lines past the orange
    assert "the orange material itself: no label may sit on it" in VIEWER
    assert 'element.dataset.movable = "suggestion"' in VIEWER  # the SUGGESTED FEATURE tag is placed too
    assert "const ty = Math.min(Math.max(sy, clearTop + hh), clearBottom - hh);" in VIEWER  # never cut at top or bottom


def test_every_dimension_says_which_value_it_is():
    assert "Program values · built in" in APP_JS and "program values, named in the program" in INDEX
    assert "Measured from photo</td>" in APP_JS and "Target · measured from photo" in APP_JS
    assert "· measured on the render`" in APP_JS and 'title="Measured on the render"' in APP_JS
    assert "Measured ${part.length_mm.toFixed(2)}" in (STATIC / "parts.js").read_text(encoding="utf-8")


def test_app_written_counts_have_correct_grammar():
    for wrong in ("} calls", "} round holes`", "BREAK CUES`", "} named parameters`", "} holes · outline"):
        assert wrong not in APP_JS, wrong
    assert "const plural = (n, word, many = `${word}s`) => `${n} ${Number(n) === 1 ? word : many}`;" in APP_JS


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_model_text_is_kept_exactly_and_only_identifiers_and_coordinates_get_code_style(tmp_path):
    regex = re.search(r"^const IDENTIFIER_OR_COORDS = .*$", APP_JS, re.M).group(0)
    start = APP_JS.index("function modelText(")
    function = APP_JS[start:APP_JS.index("\n}\n", start) + 2]
    rationale = json.loads((replay.SAMPLES_DIR / "D_tab_broken/6_completion/completion.json").read_text(encoding="utf-8"))["rationale"]
    probe = tmp_path / "probe.mjs"
    probe.write_text("const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');\n"
                     f"{regex}\n{function}\nconsole.log(modelText({json.dumps(rationale)}));\n", encoding="utf-8")
    html = subprocess.run(["node", str(probe)], capture_output=True, text=True, check=True).stdout.strip()
    codes = re.findall(r'<code class="model-code">(.*?)</code>', html)
    assert "rough_edge" in codes and "[6.94,-13.37]" in codes
    plain = re.sub(r'</?code[^>]*>', "", html).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    assert plain == rationale  # Muse Wonder's words unchanged


def test_samples_have_readable_names_and_keep_their_folder_ids():
    answer = client.get("/api/runs").json()
    titles = answer["titles"]
    assert set(titles) == set(answer["samples"]) and len(set(titles.values())) == len(titles)
    assert titles["live-20261104-220642-d6003c"] == "the run in the video (Nov 4)"
    assert titles["live-20261103-224610-c8b8df"] == "recorded live run (Nov 3)"
    assert all(titles[name] != name for name in titles)
    for name in answer["samples"]:
        assert client.get(f"/api/runs/{name}/info").json()["title"] == titles[name]
        card = gallery.card(name)
        assert card["title"] == titles[name] and card["name"] == name  # the folder stays the id
    assert 'title="${n}">${esc(titles[n] || n)}</button>' in APP_JS


def test_logo_is_the_card_mark_and_deployed_code_stays_for_iso_and_step():
    favicon = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    for svg in (favicon, INDEX[INDEX.index('<div class="rail-logo"'):INDEX.index("</div>", INDEX.index('<div class="rail-logo"'))]):
        rect = re.search(r'<rect x="3" y="7.8" width="(\d+(?:\.\d+)?)" height="(\d+(?:\.\d+)?)"', svg)
        assert rect and abs(float(rect.group(1)) / float(rect.group(2)) - 85.6 / 54) < 0.01
        circle = re.search(r'<circle cx="([\d.]+)"', svg)
        assert circle and float(circle.group(1)) > 3 + 26 * 2 / 3  # inside the right third
    assert INDEX.count("deployed_code") == 2  # iso view button and STEP card only
