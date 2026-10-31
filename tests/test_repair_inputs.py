"""Deliberately broken candidates fail the checks, and the repair request carries what Wonder needs."""
import json

import cv2
import numpy as np
import pytest

from e2e_pipeline import check_program
from part_measurements import measure_part
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette
from repair_inputs import broken_tables, build_repair_request, failure_reasons, pick_failed, write_broken_candidates

SCALE = np.diag([0.1, 0.1, 1.0])


@pytest.fixture(scope="module")
def plate():
    mask = render_top_silhouette(make_part("A"), 0.1) > 0
    return mask, measure_part(mask, SCALE)


def test_faults_change_only_what_they_name(plate):
    _, table = plate
    faults = broken_tables(table)
    assert set(faults) == {"hole_shifted", "corner_missing"}
    moved = faults["hole_shifted"]["holes"][0]["center_from_part_center_mm"]
    assert moved[0] == pytest.approx(table["holes"][0]["center_from_part_center_mm"][0] + 4)
    assert len(faults["corner_missing"]["outline"]["polygon_mm"]) == len(table["outline"]["polygon_mm"]) + 1
    assert table["outline"]["vertex_count"] == 4  # the original table is untouched


def test_broken_candidates_are_rejected_and_the_request_is_complete(plate, tmp_path):
    mask, table = plate
    rows = []
    for fault, path in write_broken_candidates(tmp_path / "broken", table):
        rows.append({"candidate": fault, **check_program(path, mask, measured_table=table)})
    assert all(not row["deviation_ok"] for row in rows), [row.get("deviation") for row in rows]

    mask_path = tmp_path / "mask.png"
    cv2.imwrite(str(mask_path), mask.astype(np.uint8) * 255)
    request = build_repair_request(tmp_path / "repair", table, mask_path, pick_failed(rows))
    assert len(request["candidates"]) == 2
    for entry in request["candidates"]:
        assert "def build_part" in entry["code"] and entry["reasons"]
        assert (tmp_path / "repair" / entry["xor_image"]).exists()
    saved = json.loads((tmp_path / "repair" / "request.json").read_text(encoding="utf-8"))
    assert saved["measurements"] and saved["mask_image"] == "mask.png"


def test_hole_count_reason_shows_counts():
    row = {"deviation": [{"dimension": "hole count", "measured_mm": 4, "candidate_mm": 3,
                          "deviation_mm": None, "limit_mm": 0, "ok": False}]}
    assert failure_reasons(row) == ["hole count: expected 4, found 3"]
