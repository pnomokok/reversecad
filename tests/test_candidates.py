"""Tests for candidate screening and execution (no API calls)."""
import numpy as np

from candidates import check_code, extract_python_block
from run_candidate import run_candidate

GOOD_CODE = """
import cadquery as cq

def build_part(length=20.0, width=10.0, thickness=2.0):
    return cq.Workplane("XY").box(length, width, thickness)
"""


def test_extracts_code_block():
    assert extract_python_block("Here:\n```python\nx = 1\n```\n") == "x = 1\n"
    assert extract_python_block("no code here") is None


def test_clean_code_passes_the_check():
    assert check_code(GOOD_CODE) == []


def test_dangerous_code_is_rejected():
    assert any("import not allowed: os" in p for p in check_code("import os\n" + GOOD_CODE))
    assert any("open" in p for p in check_code(GOOD_CODE + "\nopen('x')\n"))
    assert any("show_object" in p for p in check_code(GOOD_CODE + "\nshow_object(build_part())\n"))
    assert any("no top-level function" in p for p in check_code("import cadquery as cq\n"))


def test_good_candidate_runs_and_renders(tmp_path):
    path = tmp_path / "good.py"
    path.write_text(GOOD_CODE, encoding="utf-8")
    mask, error = run_candidate(path, 0.1)
    assert error is None
    area_mm2 = mask.sum() * 0.1**2
    assert abs(area_mm2 - 200) / 200 < 0.03


def test_broken_candidate_reports_its_error(tmp_path):
    path = tmp_path / "broken.py"
    path.write_text(GOOD_CODE.replace("box(length", "boxx(length"), encoding="utf-8")
    mask, error = run_candidate(path, 0.1)
    assert mask is None
    assert "boxx" in error
