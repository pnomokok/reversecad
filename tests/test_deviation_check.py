"""Tests for deviation_check.py on rendered parts (no API calls)."""
import cadquery as cq
import numpy as np

from deviation_check import check_deviation, tolerance
from part_measurements import measure_part
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette

SCALE = np.diag([0.1, 0.1, 1.0])


def table_of(workplane):
    return measure_part(render_top_silhouette(workplane, 0.1) > 0, SCALE)


def plate(length=80.0, holes=((-32, -12), (-32, 12), (32, -12), (32, 12))):
    part = cq.Workplane("XY").box(length, 40, 3, centered=(True, True, False))
    return part.faces(">Z").workplane().pushPoints(list(holes)).hole(6)


def test_tolerance_is_one_mm_or_two_percent():
    assert tolerance(20) == 1.0
    assert tolerance(80) == 1.6


def test_same_part_passes():
    ok, rows = check_deviation(table_of(make_part("A")), table_of(make_part("A")))
    assert ok and all(row["ok"] for row in rows)


def test_small_clean_up_is_allowed():
    ok, _ = check_deviation(table_of(plate(80)), table_of(plate(81.5)))  # 1.5 mm, limit 1.6 mm
    assert ok


def test_too_large_change_is_rejected():
    ok, rows = check_deviation(table_of(plate(80)), table_of(plate(84)))
    assert not ok
    assert [row["dimension"] for row in rows if not row["ok"]] == ["outline length"]


def test_missing_or_extra_hole_is_rejected():
    ok, rows = check_deviation(table_of(plate()), table_of(plate(holes=((-32, -12), (-32, 12), (32, -12), (32, 12),
                                                                         (0, 0)))))
    assert not ok and any(row["dimension"] == "hole count" for row in rows)
