"""Tests for partkit.py: the helpers rebuild the template parts exactly (no API calls)."""
import math

import numpy as np
import pytest

import partkit as pk
from part_measurements import check_topology, measure_part
from parts.template_parts import part_truth
from render_silhouette import render_top_silhouette

SCALE = np.diag([0.1, 0.1, 1.0])


def table_of(part):
    return measure_part(render_top_silhouette(part, 0.1) > 0, SCALE)


def area_mm2(part):
    return (render_top_silhouette(part, 0.1) > 0).sum() * 0.01


def test_plate_with_symmetric_hole_pattern_is_part_a():
    part = pk.hole_pattern(pk.plate(80, 40, 3), pk.symmetric_points(64, 24), 6)
    assert check_topology(table_of(part), part_truth("A")) == (True, [])


def test_holes_of_different_sizes_are_part_b():
    part = pk.cut_circle(pk.cut_circle(pk.plate(60, 30, 3), (-12, 0), 12), (16, 0), 6)
    assert check_topology(table_of(part), part_truth("B")) == (True, [])


def test_outline_from_points_is_part_c():
    corners = [(-35, -25), (35, -25), (35, -5), (-15, -5), (-15, 25), (-35, 25)]
    part = pk.hole_pattern(pk.outline_from_points(corners, 3), [(23, -15)], 8)
    part = pk.cut_circle(part, (-25, 13), 8)
    assert check_topology(table_of(part), part_truth("C")) == (True, [])


def test_tab_is_part_d():
    part = pk.tab(pk.plate(50, 25, 3), (0, 12.5), 12, 16, 90)
    part = pk.cut_circle(pk.cut_circle(part, (0, 0), 10), (0, 18.5), 6)
    table = table_of(part)
    assert check_topology(table, part_truth("D")) == (True, [])
    assert table["outline"]["length_mm"] == pytest.approx(50, abs=0.3)
    assert table["outline"]["width_mm"] == pytest.approx(37, abs=0.3)


def test_rectangle_and_slot_cuts_are_part_e():
    part = pk.cut_slot(pk.cut_rectangle(pk.plate(70, 40, 3), (-15, 0), 16, 8), (15, 0), 20, 6)
    assert check_topology(table_of(part), part_truth("E")) == (True, [])


def test_rotated_cuts_and_ellipse():
    part = pk.cut_ellipse(pk.cut_rectangle(pk.plate(80, 40, 3), (-20, 0), 16, 8, angle=90), (20, 0), 12, 6, 30)
    holes = {hole["shape"]: hole for hole in table_of(part)["holes"]}
    assert abs(abs(holes["rectangle"]["angle_deg"]) - 90) < 2
    assert (holes["ellipse"]["length_mm"], holes["ellipse"]["width_mm"]) == pytest.approx((12, 6), abs=0.3)
    # The render's image rows grow downward, so measured angles come out mirrored (-30 for +30).
    assert abs(abs(holes["ellipse"]["angle_deg"]) - 30) < 3


def test_grid_points_and_polygon_cut():
    assert pk.grid_points(3, 2, 10, 20) == [(-10, -10), (-10, 10), (0, -10), (0, 10), (10, -10), (10, 10)]
    part = pk.cut_polygon(pk.plate(60, 40, 3), [(-10, -10), (10, -10), (0, 10)])
    assert area_mm2(part) == pytest.approx(60 * 40 - 200, rel=0.01)


def test_semicircle_notch_removes_half_a_circle():
    part = pk.semicircle_notch(pk.plate(80, 40, 3), (40, 0), 8)
    assert area_mm2(part) == pytest.approx(80 * 40 - math.pi * 64 / 2, rel=0.01)
