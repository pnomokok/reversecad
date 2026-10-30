"""Adapter plate outline: the deterministic fallback and the checks every outline passes.

The fallback is a rounded rectangle around all holes (pattern A + placed pattern B) with
MIN_WALL_MM of margin; its program is written here with partkit, like the cover and spacer.
check_adapter scores any built outline - fallback, Muse Spark Open or Muse Wonder repair -
against the expected holes: right holes at the right positions (HOLE_TOLERANCE_MM, the same
0.5 mm the deviation check allows), every hole edge at least MIN_WALL_MM from the outline,
a single solid, no extra holes.
"""
import math

import adapter_place
from adapter_place import MIN_WALL_MM
from deviation_check import SMALL_LIMIT_MM as HOLE_TOLERANCE_MM

# Must not exceed MIN_WALL_MM: with r <= margin, a hole tucked into a corner is nearest to a
# fillet endpoint at distance >= margin + hole radius (its centre is past the arc centre in x and y),
# so the rounded corner never eats into the margin. Larger radii break small corner holes out.
FALLBACK_CORNER_RADIUS_MM = 2.0


def _point(point):
    return f"({point[0]!r}, {point[1]!r})"


def _points(name, points):
    return [f"{name} = [", *[f"    {_point(p)}," for p in points], "]", ""]


def fallback_source(holes_a, holes_b, thickness, label_b, source_program="the original"):
    """The fallback adapter program (text): a rounded rectangle with margin around every hole.

    holes_a are the original's top-face holes (circles and fixed polygons, as measured); holes_b
    are the placed pattern B circles ({"x", "y", "d"}). Only the thickness and the hole diameters
    are parameters; the outline that encloses the holes is fixed data.
    """
    groups_a, groups_b = {}, {}
    for hole in holes_a:
        if hole["type"] == "circle":
            groups_a.setdefault(hole["diameter"], []).append(hole["center"])
    for hole in holes_b:
        groups_b.setdefault(hole["d"], []).append([hole["x"], hole["y"]])
    shaped = [hole["points"] for hole in holes_a if hole["type"] != "circle"]

    extremes = []  # every hole's reach, so the rectangle encloses them all
    for diameter, centers in list(groups_a.items()) + list(groups_b.items()):
        for x, y in centers:
            extremes += [(x - diameter / 2, y - diameter / 2), (x + diameter / 2, y + diameter / 2)]
    for corners in shaped:
        extremes += [tuple(p) for p in corners]
    x0 = min(p[0] for p in extremes) - MIN_WALL_MM
    x1 = max(p[0] for p in extremes) + MIN_WALL_MM
    y0 = min(p[1] for p in extremes) - MIN_WALL_MM
    y1 = max(p[1] for p in extremes) + MIN_WALL_MM
    length, width = round(x1 - x0, 3), round(y1 - y0, 3)
    center = (round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3))
    # The margin alone makes each side over 4 mm, so a fillet always fits.
    radius = round(min(FALLBACK_CORNER_RADIUS_MM, length / 2 - 0.1, width / 2 - 0.1), 3)

    arguments = [f"    thickness={thickness!r},"]
    data = [f"CENTER = {_point(center)}", f"LENGTH = {length!r}", f"WIDTH = {width!r}", ""]
    body = ["    part = (cq.Workplane(\"XY\", origin=CENTER).rect(LENGTH, WIDTH).extrude(thickness)"
            f".edges(\"|Z\").fillet({radius!r}))"]
    for tag, groups in (("a", groups_a), ("b", groups_b)):
        for i, (diameter, centers) in enumerate(groups.items(), 1):
            parameter = f"hole_diameter_{tag}" if len(groups) == 1 else f"hole_diameter_{tag}_{i}"
            arguments.append(f"    {parameter}={diameter!r},")
            data += _points(f"ROUND_HOLES_{tag.upper()}_{i}", centers)
            body.append(f"    part = pk.hole_pattern(part, ROUND_HOLES_{tag.upper()}_{i}, {parameter})")
    if shaped:
        data += ["SHAPED_HOLES_A = [", *[f"    [{', '.join(map(_point, points))}]," for points in shaped], "]", ""]
        body += ["    for corners in SHAPED_HOLES_A:", "        part = pk.cut_polygon(part, corners)"]
    return "\n".join([
        f'"""Adapter plate matching {source_program}: pattern A plus pattern B ({label_b}).',
        "Fallback outline by adapter_outline.py: a rounded rectangle with margin around every hole.\"\"\"",
        "import cadquery as cq",
        "import partkit as pk",
        "",
        *data,
        "",
        "def build_part(",
        *arguments,
        "):",
        *body,
        "    return part",
        "",
    ])


def _describe(tag, index, hole):
    at = adapter_place.hole_center(hole)
    return f"pattern {tag} hole {index + 1} at ({at[0]:.2f}, {at[1]:.2f})"


def check_adapter(built, holes_a, holes_b):
    """{"ok", "reasons", "matched", "min_margin_mm"} for a built adapter profile.

    holes_a/holes_b are the expected holes in wall form (adapter_place.profile_hole for A,
    {"circle": (x, y, d)} for placed B). Reasons name the hole and the numbers, for the screen.
    """
    reasons = []
    if built.get("solid_count", 1) != 1:
        reasons.append(f"the program built {built.get('solid_count', 1)} solids, not one")
    expected = [("A", i, h) for i, h in enumerate(holes_a)] + [("B", i, h) for i, h in enumerate(holes_b)]
    built_holes = [adapter_place.profile_hole(h) for h in built["holes"]]

    def pair_up(want_circle):
        """Greedy closest-first pairs of expected and built holes of one kind, plus the missing."""
        wanted = [(tag, i, h) for tag, i, h in expected if ("circle" in h) == want_circle]
        have = [h for h in built_holes if ("circle" in h) == want_circle]
        distances = sorted((math.dist(adapter_place.hole_center(h), adapter_place.hole_center(g)), k, j)
                           for k, (_, _, h) in enumerate(wanted) for j, g in enumerate(have))
        pairs, taken_wanted, taken_have = [], set(), set()
        for _, k, j in distances:
            if k not in taken_wanted and j not in taken_have:
                taken_wanted.add(k)
                taken_have.add(j)
                pairs.append((wanted[k], have[j]))
        missing = [wanted[k] for k in range(len(wanted)) if k not in taken_wanted]
        extra = [have[j] for j in range(len(have)) if j not in taken_have]
        return pairs, missing, extra

    circles, missing_circles, extra_circles = pair_up(True)
    polys, missing_polys, extra_polys = pair_up(False)
    matched = 0
    for (tag, i, want), got in circles:
        position = math.dist(adapter_place.hole_center(want), adapter_place.hole_center(got))
        size = abs(want["circle"][2] - got["circle"][2])
        if position > HOLE_TOLERANCE_MM or size > HOLE_TOLERANCE_MM:
            reasons.append(f"{_describe(tag, i, want)}: built {position:.2f} mm off, "
                           f"Ø{got['circle'][2]:.2f} instead of Ø{want['circle'][2]:.2f}")
        else:
            matched += 1
    for (tag, i, want), got in polys:
        position = math.dist(adapter_place.hole_center(want), adapter_place.hole_center(got))
        corners = f"{len(got['polygon'])} corners, expected {len(want['polygon'])}" \
            if len(got["polygon"]) != len(want["polygon"]) else ""
        if position > HOLE_TOLERANCE_MM or corners:
            reasons.append(f"{_describe(tag, i, want)}: built {position:.2f} mm off"
                           + (f", {corners}" if corners else ""))
        else:
            matched += 1
    for tag, i, want in missing_circles + missing_polys:
        reasons.append(f"{_describe(tag, i, want)}: missing (no hole within {HOLE_TOLERANCE_MM} mm)")
    for got in extra_circles + extra_polys:
        at = adapter_place.hole_center(got)
        what = f"Ø{got['circle'][2]:.2f}" if "circle" in got else f"{len(got['polygon'])}-corner hole"
        reasons.append(f"extra hole at ({at[0]:.2f}, {at[1]:.2f}), {what}")
    margins = [adapter_place.hole_to_outline(h, built["outline"]) for h in built_holes]
    for hole, margin in zip(built_holes, margins):
        if margin < MIN_WALL_MM - 1e-9:
            at = adapter_place.hole_center(hole)
            reasons.append(f"hole at ({at[0]:.2f}, {at[1]:.2f}) is {margin:.2f} mm from the edge "
                           f"(at least {MIN_WALL_MM} mm needed)")
    return {"ok": not reasons, "reasons": reasons, "matched": f"{matched}/{len(expected)}",
            "min_margin_mm": round(min(margins), 3) if margins else None}
