"""Test parts from the cardboard template, with their ground truth.

A: 80 x 40 plate, four 6 mm holes 8 mm from the edges.
B: 60 x 30 plate, 12 mm hole at (18, 15) and 6 mm hole at (46, 15) (asymmetric).
C: 70 x 50 flat L plate, arms 20 mm wide, 8 mm holes at (58, 10) and (10, 38).
D: 50 x 25 body with a 16 x 12 tab in the middle of the top edge,
   10 mm hole at (25, 12.5) and 6 mm hole at (25, 31).
E: 70 x 40 plate with a 16 x 8 rectangular hole at (20, 20) and a 20 x 6 slot
   (round ends, overall length 20) at (50, 20), both along x (non-circular holes).
Coordinates are in mm from the part's bottom-left corner. A hole is
((x, y), diameter) for a circle, or ((x, y), ("rectangle" | "slot", length, width)).
"""
import math

import cadquery as cq

THICKNESS = 3.0

SPECS = {
    "A": {
        "outline": [(0, 0), (80, 0), (80, 40), (0, 40)],
        "holes": [((8, 8), 6), ((72, 8), 6), ((8, 32), 6), ((72, 32), 6)],
    },
    "B": {
        "outline": [(0, 0), (60, 0), (60, 30), (0, 30)],
        "holes": [((18, 15), 12), ((46, 15), 6)],
    },
    "C": {
        "outline": [(0, 0), (70, 0), (70, 20), (20, 20), (20, 50), (0, 50)],
        "holes": [((58, 10), 8), ((10, 38), 8)],
    },
    "D": {
        "outline": [(0, 0), (50, 0), (50, 25), (33, 25), (33, 37), (17, 37), (17, 25), (0, 25)],
        "holes": [((25, 12.5), 10), ((25, 31), 6)],
    },
    "E": {
        "outline": [(0, 0), (70, 0), (70, 40), (0, 40)],
        "holes": [((20, 20), ("rectangle", 16, 8)), ((50, 20), ("slot", 20, 6))],
    },
}


def _hole_cutter(x, y, size, thickness):
    """A solid that cuts the hole, reaching a little past both faces."""
    workplane = cq.Workplane("XY", origin=(x, y, -1))
    if isinstance(size, tuple):
        shape, length, width = size
        sketch = workplane.rect(length, width) if shape == "rectangle" else workplane.slot2D(length, width)
        return sketch.extrude(thickness + 2)
    return workplane.circle(size / 2).extrude(thickness + 2)


def make_part(name, thickness=THICKNESS):
    """Extruded outline with through-holes."""
    spec = SPECS[name]
    part = cq.Workplane("XY").polyline(spec["outline"]).close().extrude(thickness)
    for (x, y), size in spec["holes"]:
        part = part.cut(_hole_cutter(x, y, size, thickness))
    return part


def _truth_hole(x, y, size, cx, cy):
    hole = {"center_from_part_center_mm": [x - cx, y - cy]}
    if not isinstance(size, tuple):
        return {**hole, "shape": "circle", "diameter_mm": size}
    shape, length, width = size
    area = length * width if shape == "rectangle" else (length - width) * width + math.pi * width**2 / 4
    # diameter_mm of a non-circular hole is the diameter of a circle with the same area
    return {**hole, "shape": shape, "length_mm": length, "width_mm": width, "angle_deg": 0.0,
            "diameter_mm": round(2 * math.sqrt(area / math.pi), 3)}


def part_truth(name):
    """Ground truth of a template part in the measurement table's frame: [u, v] from the bounding-rectangle center."""
    return truth_from_spec(SPECS[name], name)


def truth_from_spec(spec, name="part"):
    """Ground truth of any spec ({"outline", "holes"}, mm) in the measurement table's frame. The table puts u
    along the longer side, so a part that is longer in y is turned 90 degrees first."""
    outline, holes = spec["outline"], spec["holes"]
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    if max(ys) - min(ys) > max(xs) - min(xs):  # turn (x, y) -> (y, -x); elongated holes turn with it
        outline = [(y, -x) for x, y in outline]
        holes = [((y, -x), (size[0], size[1], size[2]) if isinstance(size, tuple) else size) for (x, y), size in holes]
        turned = True
    else:
        turned = False
    xs = [x for x, _ in outline]
    ys = [y for _, y in outline]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    width_x, width_y = max(xs) - min(xs), max(ys) - min(ys)
    truth_holes = [_truth_hole(x, y, size, cx, cy) for (x, y), size in holes]
    if turned:
        for hole in truth_holes:
            if "angle_deg" in hole:
                hole["angle_deg"] = 90.0
    return {
        "name": name,
        "length": width_x,
        "width": width_y,
        "thickness": THICKNESS,
        "outline_vertices": len(outline),
        "outline_mm": [[x - cx, y - cy] for x, y in outline],
        "holes": truth_holes,
    }
