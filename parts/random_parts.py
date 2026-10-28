"""Random flat parts for the large synthetic test, each with its true design (and, for broken ones, the damage).

Families: a plate, a flat L and a body with a tab. Hole layouts: none, one, a symmetric pair, four corners,
a 2 x 3 grid, sometimes a slot or a rectangular hole. A share of the parts is broken: a chipped corner,
a snapped-off tab or a hole that was never drilled (parts/broken_parts.jagged_line for break edges).
A part is a spec like template_parts.SPECS ({"outline", "holes"}, mm from the bottom-left corner);
random_part(seed) always gives the same part for the same seed.
"""
import math
import random

from parts.broken_parts import _with_holes, jagged_line
from parts.template_parts import THICKNESS, truth_from_spec

FAMILIES = ("plate", "l_shape", "tab")
BROKEN_SHARE = 0.3
EDGE_CLEARANCE_MM = 2.5  # wall left between a hole and an edge or another hole


def _plate(rng):
    length, width = rng.uniform(40, 120), rng.uniform(20, 70)
    if width > length:
        length, width = width, length
    return {"outline": [(0, 0), (length, 0), (length, width), (0, width)], "box": (length, width),
            "regions": [(0, 0, length, width)]}


def _l_shape(rng):
    length, width = rng.uniform(50, 110), rng.uniform(35, 80)
    arm_x, arm_y = rng.uniform(15, width * 0.6), rng.uniform(15, length * 0.45)
    return {"outline": [(0, 0), (length, 0), (length, arm_x), (arm_y, arm_x), (arm_y, width), (0, width)],
            "box": (length, width), "regions": [(0, 0, length, arm_x), (0, 0, arm_y, width)]}


def _tab(rng):
    length, width = rng.uniform(40, 100), rng.uniform(20, 50)
    tab_w, tab_h = rng.uniform(10, min(30, length * 0.5)), rng.uniform(8, 18)
    left = (length - tab_w) / 2
    return {"outline": [(0, 0), (length, 0), (length, width), (left + tab_w, width), (left + tab_w, width + tab_h),
                        (left, width + tab_h), (left, width), (0, width)],
            "box": (length, width + tab_h), "regions": [(0, 0, length, width), (left, width, left + tab_w, width + tab_h)],
            "tab": (left, width, tab_w, tab_h)}


def _fits(center, radius, regions, holes):
    """The hole lies inside one material region with clearance, and clear of the other holes."""
    x, y = center
    inside = any(x0 + radius + EDGE_CLEARANCE_MM <= x <= x1 - radius - EDGE_CLEARANCE_MM
                 and y0 + radius + EDGE_CLEARANCE_MM <= y <= y1 - radius - EDGE_CLEARANCE_MM
                 for x0, y0, x1, y1 in regions)
    return inside and all(math.dist(center, c) >= radius + r + EDGE_CLEARANCE_MM for c, r in holes)


def _layout(rng, shape):
    """Hole centers and one diameter for a layout chosen at random (positions on the main region)."""
    x0, y0, x1, y1 = shape["regions"][0]
    length, width = x1 - x0, y1 - y0
    diameter = round(rng.uniform(3, min(10, width / 3)), 1)
    margin = rng.uniform(diameter / 2 + 3, min(12, width / 3))
    layout = rng.choice(["none", "one", "pair", "corners", "corners", "grid"])
    cx, cy = x0 + length / 2, y0 + width / 2
    centers = {"none": [], "one": [(cx, cy)],
               "pair": [(x0 + margin, cy), (x1 - margin, cy)],
               "corners": [(x0 + margin, y0 + margin), (x1 - margin, y0 + margin),
                           (x0 + margin, y1 - margin), (x1 - margin, y1 - margin)],
               "grid": [(x0 + margin + i * (length - 2 * margin) / 2, y0 + margin + j * (width - 2 * margin))
                        for i in range(3) for j in range(2)]}[layout]
    return layout, centers, diameter


def random_part(seed):
    """{"name", "family", "layout", "broken": damage or None, "spec", "design"}; spec is what is built,
    design the intact part (the truth to compare a completion with)."""
    rng = random.Random(seed)
    family = rng.choice(FAMILIES)
    shape = {"plate": _plate, "l_shape": _l_shape, "tab": _tab}[family](rng)
    layout, centers, diameter = _layout(rng, shape)
    holes, placed = [], []
    for center in centers:
        if _fits(center, diameter / 2, shape["regions"], placed):
            holes.append(((round(center[0], 2), round(center[1], 2)), diameter))
            placed.append((center, diameter / 2))
    if family == "tab" and rng.random() < 0.5:  # a hole in the tab
        left, base, tab_w, tab_h = shape["tab"]
        center, tab_hole = (left + tab_w / 2, base + tab_h / 2), round(min(tab_w, tab_h) * 0.4, 1)
        if _fits(center, tab_hole / 2, shape["regions"][1:], placed):
            holes.append(((round(center[0], 2), round(center[1], 2)), tab_hole))
    if family == "plate" and rng.random() < 0.25:  # a slot or a rectangular hole in the middle
        length, width = shape["box"]
        slot = ("slot" if rng.random() < 0.5 else "rectangle", round(min(20, length / 4), 1), round(min(6, width / 5), 1))
        center = (length / 2, width / 2)
        if all(math.dist(center, c) > slot[1] / 2 + r + EDGE_CLEARANCE_MM for c, r in placed):
            holes.append(((round(center[0], 2), round(center[1], 2)), slot))
    outline = [(round(x, 2), round(y, 2)) for x, y in shape["outline"]]
    design = {"outline": outline, "holes": holes}

    broken = None
    if rng.random() < BROKEN_SHARE:
        broken, spec = _break(rng, family, shape, design, seed)
    else:
        spec = design
    return {"name": f"R{seed:03d}", "family": family, "layout": layout, "broken": broken, "spec": spec, "design": design}


def _break(rng, family, shape, design, seed):
    """(damage, broken spec) for one kind of damage the part can have."""
    kinds = ["missing_hole"] if len([h for h in design["holes"] if not isinstance(h[1], tuple)]) >= 2 else []
    kinds += ["chipped_corner"]
    kinds += ["snapped_tab"] if family == "tab" else []
    kind = rng.choice(kinds)
    if kind == "missing_hole":
        holes = list(design["holes"])
        holes.pop(rng.randrange(len([h for h in holes if not isinstance(h[1], tuple)])))
        return "missing_hole", {"outline": design["outline"], "holes": holes}
    if kind == "snapped_tab":
        left, base, tab_w, tab_h = shape["tab"]
        stub = rng.uniform(1.5, tab_h * 0.4)
        outline = [p for p in design["outline"] if p[1] <= base + 1e-2]  # the body (the outline is rounded to 0.01)
        i = next(k for k, p in enumerate(outline) if abs(p[0] - (left + tab_w)) < 1e-2)
        top = jagged_line((left + tab_w, base + stub), (left, base + stub), seed)[1:-1]
        outline = outline[:i + 1] + [(left + tab_w, base + stub)] + top + [(left, base + stub)] + outline[i + 1:]
        holes = [h for h in design["holes"] if h[0][1] < base]
        return "snapped_tab", {"outline": outline, "holes": holes}
    # chipped corner: the top-right corner of the box breaks off along a jagged line (never through a hole)
    length = shape["box"][0]
    corner = max(design["outline"], key=lambda p: p[0] + p[1])
    size = rng.uniform(6, 14)
    start, end = (corner[0], corner[1] - size), (corner[0] - size, corner[1])
    if any(math.dist(c, corner) < size * 0.75 + (d if not isinstance(d, tuple) else d[1]) for c, d in design["holes"]):
        return None, design  # the break would run through a hole: leave this part intact
    i = design["outline"].index(corner)
    outline = design["outline"][:i] + jagged_line(start, end, seed) + design["outline"][i + 1:]
    return "chipped_corner", {"outline": outline, "holes": design["holes"]}


def make_random_part(part, which="spec", thickness=THICKNESS):
    """The part (or its intact design) as a CadQuery solid."""
    spec = part[which]
    return _with_holes(spec["outline"], spec["holes"], thickness)


def truth_of(part, which="design"):
    """Ground truth in the measurement table's frame (template_parts.truth_from_spec)."""
    return truth_from_spec(part[which], part["name"])
