"""Broken versions of the template parts, for testing break cues and completion; the intact design is known.

Each broken part is the template's design with damage: material removed behind a jagged break line
(a torn or snapped edge zigzags; a designed edge is straight), or a hole that was never made.

  A_chipped:      A with its top-right corner broken off (the hole near it stays whole).
  A_half_hole:    A with its top-right corner broken off through the hole there (half of it remains).
  A_missing_hole: A with its bottom-right hole never drilled (no break, a gap in the pattern).
  A_torn:         A with its top and right edges torn along their whole length (irregular, nothing missing).
  D_tab_broken:   D with the tab snapped off 2 mm above the body (its 6 mm hole is lost with it).

Coordinates are in mm from the part's bottom-left corner, as in template_parts.SPECS.
"""
import cadquery as cq
import numpy as np

from parts.template_parts import SPECS, THICKNESS, _hole_cutter, part_truth

ZIGZAG_MM = 0.6  # amplitude of the break's zigzag
ZIGZAG_STEP_MM = 1.5


def jagged_line(start, end, seed):
    """Points from start to end with a deterministic zigzag across the line (a break, not a cut)."""
    start, end = np.array(start, float), np.array(end, float)
    length = np.linalg.norm(end - start)
    across = np.array([-(end - start)[1], (end - start)[0]]) / length
    steps = max(int(length / ZIGZAG_STEP_MM), 2)
    offsets = np.random.default_rng(seed).uniform(-ZIGZAG_MM, ZIGZAG_MM, steps + 1)
    offsets[0] = offsets[-1] = 0.0  # meet the intact outline exactly
    return [tuple(start + (end - start) * i / steps + across * offsets[i]) for i in range(steps + 1)]


def _with_holes(outline, holes, thickness):
    part = cq.Workplane("XY").polyline(outline).close().extrude(thickness)
    for (x, y), size in holes:
        part = part.cut(_hole_cutter(x, y, size, thickness))
    return part


BROKEN = {
    "A_chipped": {
        "design": "A",
        "damage": "top-right corner broken off along a line from (80, 30) to (68, 40); the hole at (72, 32) stays whole",
        "outline": [(0, 0), (80, 0), *jagged_line((80, 30), (68, 40), seed=1), (0, 40)],
        "holes": SPECS["A"]["holes"],
    },
    "A_half_hole": {
        "design": "A",
        "damage": "top-right corner broken off along a line from (80, 24) to (64, 40), through the hole at (72, 32)",
        "outline": [(0, 0), (80, 0), *jagged_line((80, 24), (64, 40), seed=2), (0, 40)],
        "holes": SPECS["A"]["holes"],
    },
    "A_missing_hole": {
        "design": "A",
        "damage": "the hole at (72, 8) was never drilled",
        "outline": SPECS["A"]["outline"],
        "holes": [hole for hole in SPECS["A"]["holes"] if hole[0] != (72, 8)],
    },
    "A_torn": {
        "design": "A",
        "damage": "top and right edges torn along their whole length (hand-cut or torn, nothing broken off)",
        "outline": [(0, 0), *jagged_line((80, 0), (80, 40), seed=4)[:-1], *jagged_line((80, 40), (0, 40), seed=5)],
        "holes": SPECS["A"]["holes"],
    },
    "D_tab_broken": {
        "design": "D",
        "damage": "the 16 x 12 tab snapped off 2 mm above the body; its 6 mm hole at (25, 31) is lost",
        "outline": [(0, 0), (50, 0), (50, 25), (33, 25), (33, 27), *jagged_line((33, 27), (17, 27), seed=3)[1:-1],
                    (17, 27), (17, 25), (0, 25)],
        "holes": [((25, 12.5), 10)],
    },
}


def make_broken_part(name, thickness=THICKNESS):
    """The broken part as a CadQuery solid."""
    spec = BROKEN[name]
    return _with_holes(spec["outline"], spec["holes"], thickness)


def design_truth(name):
    """The intact design the broken part was made from (template_parts.part_truth of its design)."""
    return part_truth(BROKEN[name]["design"])
