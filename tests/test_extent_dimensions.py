"""Capture overlay: each extent is drawn parallel to the axis it measures.

The part's length and width come from cv2.minAreaRect (part_measurements.measure_part). The
overlay must draw each extent along that same rectangle's sides — length along a long side, width
along a short side — just outside the shape, with extension lines square to it. A principal-axis
box is not enough: for a nearly square part it tilts to about 45 degrees and the extents come
out diagonal (seen on the recorded live sample). The probe runs the shipped JavaScript in Node.
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
PROBE = ROOT / "tests" / "extent_probe.mjs"
APP = ROOT / "webapp" / "static" / "app.js"
SAMPLES = ["live-20261103-224610-c8b8df", "A_light", "C_wood", "D_tab_broken"]

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def rotated(points, degrees, center=(400.0, 300.0)):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return [[center[0] + x * c - y * s, center[1] + x * s + y * c] for x, y in points]


def synthetic_cases():
    # A 200 x 100 plate turned 30 degrees, and a nearly square plate with one chamfered corner
    # (like the live sample: its principal axes sit near 45 degrees, its sides near 0).
    plate = [[-100, -50], [100, -50], [100, 50], [-100, 50]]
    chamfered = [[-107, -97], [107, -97], [107, 60], [70, 97], [-107, 97]]
    return [{"name": "plate_30deg", "points": rotated(plate, 30)},
            {"name": "near_square_chamfer", "points": rotated(chamfered, 2)}]


def sample_cases():
    from webapp import replay
    cases = []
    for name in SAMPLES:
        try:
            a = replay.analysis(name)
        except FileNotFoundError:
            continue
        cases.append({"name": f"{name}:part", "points": a["outline_px"]})
        cases.append({"name": f"{name}:card", "points": a["card_corners_px"]})
    return cases


def unit(p, q):
    d = np.subtract(q, p, dtype=float)
    return d / np.linalg.norm(d)


def angle_between_lines(d1, d2):
    """Angle in degrees between two undirected directions."""
    return math.degrees(math.acos(min(1.0, abs(float(np.dot(d1, d2))))))


def rect_sides(points):
    """cv2.minAreaRect's long and short side: (direction, length) each."""
    corners = cv2.boxPoints(cv2.minAreaRect(np.array(points, dtype=np.float32)))
    e1, e2 = corners[1] - corners[0], corners[2] - corners[1]
    sides = sorted([(e1, np.linalg.norm(e1)), (e2, np.linalg.norm(e2))], key=lambda s: -s[1])
    return [(d / n, n) for d, n in sides]


@needs_node
def test_extent_lines_parallel_to_measured_axis(tmp_path):
    cases = synthetic_cases() + sample_cases()
    assert len(cases) >= 2 + 2 * len(SAMPLES), "the bundled samples should all load"
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases), encoding="utf-8")
    run = subprocess.run(["node", str(PROBE), str(APP), str(path)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr.strip() or run.stdout.strip()
    results = json.loads(run.stdout)

    for case, result in zip(cases, results):
        points = np.array(case["points"], dtype=float)
        (long_dir, long_len), (short_dir, short_len) = rect_sides(case["points"])
        for dim in result["dims"]:
            name = f"{case['name']} {dim['along']} side {dim['side']}"
            a, b = np.array(dim["a"]), np.array(dim["b"])
            measured_dir, measured_len = (long_dir, long_len) if dim["along"] == "u" else (short_dir, short_len)
            direction = unit(a, b)
            # Rule 1: parallel to the axis it measures, and as long as the measured extent.
            assert angle_between_lines(direction, measured_dir) < 0.5, name
            assert abs(np.linalg.norm(b - a) - measured_len) <= max(1.0, 0.005 * measured_len), name
            # Just outside the shape: every outline point lies on the inner side of the line.
            normal = np.array([-direction[1], direction[0]])
            offsets = (points - a) @ normal
            assert offsets.max() < 0 or offsets.min() > 0, name
            # Extension lines: square to the dimension line, through its two ends, reaching past it.
            for (p, q), end in zip(dim["ext"], (a, b)):
                p, q = np.array(p), np.array(q)
                assert angle_between_lines(unit(p, q), normal) < 0.5, name
                assert abs(float(np.dot(end - p, direction))) < 1e-6, name
                assert np.dot(q - end, p - end) < 0, name  # the line sits between p and q
