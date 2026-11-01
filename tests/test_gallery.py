"""Parts gallery: card fields from saved files, private exclusion, unfinished exclusion."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from webapp import gallery, replay
from webapp.server import app

TABLE = {"outline": {"length_mm": 80.0, "width_mm": 40.0}, "holes": [{}, {}, {}]}


def _write_run(folder, source="candidate", private=False, summary=True):
    folder.mkdir(parents=True)
    (folder / "3_measurements.json").write_text(json.dumps({"table": TABLE}), encoding="utf-8")
    if summary:
        (folder / "5_summary_candidates_arcs_effort_medium.json").write_text(
            json.dumps({"result": {"file": "candidates_arcs_effort_medium/c1.py"},
                        "result_source": source}), encoding="utf-8")
    if private:
        (folder / "private.txt").write_text("Private: test marker\n", encoding="utf-8")


def test_card_fields_come_from_saved_files(tmp_path, monkeypatch):
    """Size, holes, source and kind mirror the run folder; a new folder needs no code."""
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    _write_run(tmp_path / "plate")
    assert gallery.card("plate") == {"name": "plate", "length_mm": 80.0, "width_mm": 40.0,
                                      "hole_count": 3, "source": "Winner", "kind": "Synthetic"}


def test_source_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    assert gallery.source_label("candidate") == "Winner"
    assert gallery.source_label("repair \u00b7 Muse Wonder") == "Muse Wonder repair"
    assert gallery.source_label("fallback: measured shape, no design intent") == "Fallback"
    assert gallery.source_label(replay.COMPLETION_SOURCE) == "Completion applied"
    assert gallery.source_label("something new") is None


def test_live_name_means_real_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    _write_run(tmp_path / "live-20990101-000000-abcdef")
    assert gallery.card("live-20990101-000000-abcdef")["kind"] == "Real photo"


def test_private_marker_excludes(tmp_path, monkeypatch):
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    _write_run(tmp_path / "shown")
    _write_run(tmp_path / "hidden", private=True)
    assert gallery.is_private(tmp_path / "hidden")
    assert not gallery.is_private(tmp_path / "shown")
    assert [c["name"] for c in gallery.gallery_runs()] == ["shown"]


def test_unfinished_run_has_no_card(tmp_path, monkeypatch):
    """Measured but no candidate round yet: skipped, never a guessed card."""
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    _write_run(tmp_path / "measuring", summary=False)
    assert gallery.card("measuring") is None
    assert gallery.gallery_runs() == []


def test_samples_keep_their_cards():
    """The committed samples: pinned sources, sizes and hole counts."""
    assert gallery.card("A_light") == {"name": "A_light", "length_mm": pytest.approx(79.46, abs=0.01),
                                        "width_mm": pytest.approx(40.54, abs=0.01), "hole_count": 4,
                                        "source": "Winner", "kind": "Synthetic"}
    assert gallery.card("A_light_repair")["source"] == "Muse Wonder repair"
    assert gallery.card("A_torn_fallback")["source"] == "Fallback"
    assert gallery.card("D_tab_broken")["source"] == "Winner"


def test_demo_sources_list_samples_only(monkeypatch):
    """The demo narrows SOURCES to samples/; the gallery follows it with no extra code."""
    monkeypatch.setattr(replay, "SOURCES", [replay.SAMPLES_DIR])
    names = {c["name"] for c in gallery.gallery_runs()}
    assert names == {"A_light", "A_light_repair", "A_torn_fallback", "D_tab_broken"}


def test_parts_endpoint_shape():
    """GET /api/parts: every card carries the six fields; marked runs never appear."""
    body = TestClient(app).get("/api/parts").json()
    assert isinstance(body["parts"], list) and body["parts"]
    for card in body["parts"]:
        assert sorted(card) == ["hole_count", "kind", "length_mm", "name", "source", "width_mm"]
    names = {c["name"] for c in body["parts"]}
    assert "live-20261031-161042-2ab58f" not in names  # marked private on this machine
    assert "A_light" in names


def test_run_files_untouched(tmp_path, monkeypatch):
    """Reading cards writes nothing into the run folder."""
    monkeypatch.setattr(replay, "SOURCES", [tmp_path])
    _write_run(tmp_path / "plate")
    before = sorted(p.name for p in (tmp_path / "plate").iterdir())
    gallery.gallery_runs()
    assert sorted(p.name for p in (tmp_path / "plate").iterdir()) == before
