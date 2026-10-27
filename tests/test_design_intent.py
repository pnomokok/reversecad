"""Tests for design_intent.py and baseline_cad.py (no API calls).

A hand-written plate with designer-style parameters must pass every intent
check; the baseline built from the same plate's measurements must fail them.
"""
import numpy as np

from baseline_cad import baseline_code
from design_intent import evaluate, parameters, symmetry_axes
from part_measurements import check_topology, measure_part
from parts.template_parts import make_part, part_truth
from render_silhouette import render_top_silhouette
from run_candidate import run_candidate

INTENT_CODE = """
import cadquery as cq

def build_part(length=80.0, width=40.0, thickness=3.0, hole_diameter=6.0, edge_margin=8.0):
    points = [(x * (length / 2 - edge_margin), y * (width / 2 - edge_margin)) for x in (-1, 1) for y in (-1, 1)]
    return (cq.Workplane("XY").box(length, width, thickness, centered=(True, True, False))
            .faces(">Z").workplane().pushPoints(points).hole(hole_diameter))
"""


def test_symmetry_axes_of_template_parts():
    assert symmetry_axes(part_truth("A")) == ["left-right", "top-bottom"]
    assert symmetry_axes(part_truth("B")) == ["top-bottom"]  # both holes lie on the center line
    assert symmetry_axes(part_truth("C")) == []
    assert symmetry_axes(part_truth("D")) == ["left-right"]


def test_designer_style_plate_passes_every_check(tmp_path):
    path = tmp_path / "intent.py"
    path.write_text(INTENT_CODE, encoding="utf-8")
    report = evaluate(path, part_truth("A"))
    assert report["parameter_count"] == 5
    assert report["hole_diameter_linked"] is True and report["hole_diameter_parameter"] == ["hole_diameter"]
    assert report["length_parameter"] == "length"
    assert report["symmetric_after_length_change"] is True
    assert report["edge_margin_kept"] is True


def test_baseline_cuts_rectangular_holes_and_slots(tmp_path):
    scale = np.diag([0.1, 0.1, 1.0])
    table = measure_part(render_top_silhouette(make_part("E"), 0.1) > 0, scale)
    path = tmp_path / "baseline_e.py"
    path.write_text(baseline_code(table), encoding="utf-8")
    mask, error = run_candidate(path, 0.1)
    assert error is None
    assert check_topology(measure_part(mask, scale), part_truth("E")) == (True, [])


def test_baseline_reproduces_the_shape_but_carries_no_intent(tmp_path):
    table = measure_part(render_top_silhouette(make_part("A"), 0.1) > 0, np.diag([0.1, 0.1, 1.0]))
    path = tmp_path / "baseline.py"
    path.write_text(baseline_code(table), encoding="utf-8")
    assert len(parameters(path.read_text(encoding="utf-8"))) == 1 + 2 * 4 + 3 * 4

    mask, error = run_candidate(path, 0.1)
    assert error is None
    assert check_topology(measure_part(mask, np.diag([0.1, 0.1, 1.0])), part_truth("A"))[0]

    report = evaluate(path, part_truth("A"))
    assert report["hole_diameter_linked"] is False
    assert report["length_parameter"] is None
    assert report["symmetric_after_length_change"] is False
    assert report["edge_margin_kept"] is False
