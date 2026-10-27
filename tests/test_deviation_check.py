"""Tests for deviation_check.py and model_view.py on rendered parts (no API calls)."""
import cadquery as cq
import numpy as np

import partkit as pk
from deviation_check import check_deviation, tolerance
from model_view import model_view
from part_measurements import measure_part
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette

SCALE = np.diag([0.1, 0.1, 1.0])


def table_of(workplane):
    return measure_part(render_top_silhouette(workplane, 0.1) > 0, SCALE)


def plate(length=80.0, holes=((-32, -12), (-32, 12), (32, -12), (32, 12)), hole_diameter=6.0):
    part = cq.Workplane("XY").box(length, 40, 3, centered=(True, True, False))
    return part.faces(">Z").workplane().pushPoints(list(holes)).hole(hole_diameter)


def failing(rows):
    return [row["dimension"] for row in rows if not row["ok"]]


def test_tolerance():
    assert tolerance(12) == 0.5  # small features
    assert tolerance(40) == 1.0
    assert tolerance(80) == 1.6


def test_same_part_passes():
    ok, rows = check_deviation(model_view(table_of(make_part("A"))), table_of(make_part("A")))
    assert ok, failing(rows)


def test_small_clean_up_of_the_outline_is_allowed():
    ok, rows = check_deviation(model_view(table_of(plate(80))), table_of(plate(81.5)))  # limit 1.6 mm
    assert ok, failing(rows)


def test_too_large_outline_change_is_rejected():
    ok, rows = check_deviation(model_view(table_of(plate(80))), table_of(plate(84)))
    assert not ok and "outline length" in failing(rows)


def test_holes_get_half_a_millimeter():
    ok, _ = check_deviation(model_view(table_of(plate())), table_of(plate(hole_diameter=6.3)))
    assert ok
    ok, rows = check_deviation(model_view(table_of(plate())), table_of(plate(hole_diameter=7.0)))
    assert not ok and "hole 1 diameter" in failing(rows)
    moved = ((-31, -12), (-32, 12), (32, -12), (32, 12))  # one hole 1 mm off
    ok, rows = check_deviation(model_view(table_of(plate())), table_of(plate(holes=moved)))
    assert not ok and any("position" in name for name in failing(rows))


def test_missing_tab_is_rejected():
    body = pk.plate(50, 25, 3)
    with_tab = pk.tab(body, (0, 12.5), 12, 16, 90)
    ok, rows = check_deviation(model_view(table_of(with_tab)), table_of(pk.tab(body, (0, 12.5), 12, 14, 90)))
    assert not ok and any(name.startswith("corner") for name in failing(rows))  # tab 2 mm too narrow


def test_model_view_gives_notches_and_rounded_corners_as_arcs():
    notched = model_view(table_of(pk.semicircle_notch(pk.plate(80, 40, 3), (40, 0), 8)))["outline"]
    assert notched["vertex_count"] == 6 and len(notched["arcs"]) == 1
    assert abs(notched["arcs"][0]["radius_mm"] - 8) < 0.3
    filleted = model_view(table_of(cq.Workplane("XY").box(80, 40, 3, centered=(True, True, False))
                                   .edges("|Z").fillet(5)))["outline"]
    assert len(filleted["arcs"]) == 4
    assert all(abs(arc["radius_mm"] - 5) < 0.5 for arc in filleted["arcs"])
    assert model_view(table_of(make_part("D")))["outline"]["arcs"] == []  # straight-edged parts get no arcs


def test_notch_radius_is_checked_on_the_arc():
    view = model_view(table_of(pk.semicircle_notch(pk.plate(80, 40, 3), (40, 0), 8)))
    ok, rows = check_deviation(view, table_of(pk.semicircle_notch(pk.plate(80, 40, 3), (40, 0), 8)))
    assert ok, failing(rows)
    ok, rows = check_deviation(view, table_of(pk.semicircle_notch(pk.plate(80, 40, 3), (40, 0), 9)))
    assert not ok and "arc 1" in failing(rows)


def test_extra_hole_is_rejected():
    extra = ((-32, -12), (-32, 12), (32, -12), (32, 12), (0, 0))
    ok, rows = check_deviation(model_view(table_of(plate())), table_of(plate(holes=extra)))
    assert not ok and "hole count" in failing(rows)
