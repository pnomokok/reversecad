"""Place pattern B relative to pattern A: deterministic candidates, no language model.

Pattern A is the original part's holes (from its built top-face profile); pattern B is the
validated new pattern, relative to its own centre. Candidates, in order: centred on A, centred
plus rotated 90 degrees, then offsets along the plate's long axis. The first candidate where
every hole-to-hole wall (A-A, A-B, B-B) is at least MIN_WALL_MM wins; else the patterns cannot
be placed. Walls are exact boundary distances (circles and shaped-hole polygons); a hole inside
another counts as a negative wall.
"""
import math

# Minimum material between any two hole edges (A-A, A-B, B-B) and between a hole edge and the
# plate outline (the adapter checks reuse it as the edge margin). A geometric feasibility rule so
# holes neither merge nor break out - not a strength rule, it says nothing about loads.
MIN_WALL_MM = 2.0

# Offsets along the plate's long axis, each tried plain and rotated 90 degrees, after the two
# centred candidates. Short and fixed, so placement never depends on a model.
PLACEMENT_OFFSETS_MM = (10.0, 20.0, 30.0)


def _point_to_segment(point, a, b):
    px, py = point
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    t = 0.0 if length_squared == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.dist(point, (ax + t * dx, ay + t * dy))


def _segments_cross(a, b, c, d):
    """True when the segments AB and CD cross (for segment-segment distance)."""
    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0


def _segment_distance(a, b, c, d):
    if _segments_cross(a, b, c, d):
        return 0.0
    return min(_point_to_segment(a, c, d), _point_to_segment(b, c, d),
               _point_to_segment(c, a, b), _point_to_segment(d, a, b))


def _point_in_polygon(point, corners):
    """Ray casting; a point on an edge counts as inside."""
    x, y = point
    inside = False
    ring = corners + corners[:1]
    for (ax, ay), (bx, by) in zip(ring, ring[1:]):
        if min(ay, by) < y <= max(ay, by) and x <= max(ax, bx):
            crossing = ax if ay == by else ax + (y - ay) * (bx - ax) / (by - ay)
            if x <= crossing:
                inside = not inside
    return inside


def _circle_to_polygon(center, radius, corners):
    edges = list(zip(corners, corners[1:] + corners[:1]))
    gap = min(_point_to_segment(center, a, b) for a, b in edges) - radius
    return -abs(gap) - radius if _point_in_polygon(center, corners) else gap


def _polygon_to_polygon(first, second):
    first_edges = list(zip(first, first[1:] + first[:1]))
    second_edges = list(zip(second, second[1:] + second[:1]))
    gap = min(_segment_distance(a, b, c, d) for a, b in first_edges for c, d in second_edges)
    nested = _point_in_polygon(first[0], second) or _point_in_polygon(second[0], first)
    return -gap if nested and gap > 0 else gap


def hole_wall(first, second):
    """Signed wall (mm) between two holes: {"circle": (x, y, d)} or {"polygon": [(x, y), ...]}.

    The smallest distance between their boundaries; negative when they overlap or nest.
    """
    if "circle" in first and "circle" in second:
        (x0, y0, d0), (x1, y1, d1) = first["circle"], second["circle"]
        return math.dist((x0, y0), (x1, y1)) - (d0 + d1) / 2
    if "circle" in first:
        (x, y, d), corners = first["circle"], second["polygon"]
        return _circle_to_polygon((x, y), d / 2, corners)
    if "circle" in second:
        (x, y, d), corners = second["circle"], first["polygon"]
        return _circle_to_polygon((x, y), d / 2, corners)
    return _polygon_to_polygon(first["polygon"], second["polygon"])


def _profile_hole(hole):
    """A built profile's hole in wall form."""
    if hole["type"] == "circle":
        (x, y), d = hole["center"], hole["diameter"]
        return {"circle": (x, y, d)}
    return {"polygon": [tuple(p) for p in hole["points"]]}


def _hole_center(hole):
    if "circle" in hole:
        return hole["circle"][:2]
    xs, ys = zip(*hole["polygon"])
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def place_pattern(profile, pattern):
    """Place pattern B's holes onto the profile's (absolute) coordinates.

    Returns {"candidate", "holes_b": [{"x", "y", "d"}], "walls": {"aa", "ab", "bb", "min"}} or None
    when no candidate keeps every wall at MIN_WALL_MM. profile is the built original's top face
    (outline box, holes); pattern is a validated pattern B (holes relative to its centre).
    """
    holes_a = [_profile_hole(h) for h in profile["holes"]]
    holes_b = [{"circle": (h["x"], h["y"], h["d"])} for h in pattern["holes"]]
    pairs = lambda holes: [hole_wall(a, b) for i, a in enumerate(holes) for b in holes[i + 1:]]
    wall_aa = min(pairs(holes_a), default=None)  # None with fewer than two holes (nothing to check)
    wall_bb = min(pairs(holes_b), default=None)
    if (wall_aa is not None and wall_aa < MIN_WALL_MM) or (wall_bb is not None and wall_bb < MIN_WALL_MM):
        return None  # rigid motions cannot fix A-A or B-B: no candidate can pass
    if holes_a:
        center = [sum(c[i] for c in map(_hole_center, holes_a)) / len(holes_a) for i in (0, 1)]
    else:  # no pattern A: centre on the plate instead
        box = profile["box"]
        center = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
    box = profile["box"]
    long_axis = (1.0, 0.0) if box[2] - box[0] >= box[3] - box[1] else (0.0, 1.0)
    candidates = [("centred", 0.0, False), ("centred + rotated 90°", 0.0, True)]
    for offset in PLACEMENT_OFFSETS_MM:
        for signed in (offset, -offset):
            sign = "+" if signed > 0 else "−"
            candidates.append((f"offset {sign}{offset:g} mm", signed, False))
            candidates.append((f"offset {sign}{offset:g} mm + rotated 90°", signed, True))
    for name, offset, rotated in candidates:
        moved = []
        for hole in pattern["holes"]:
            x, y = (-hole["y"], hole["x"]) if rotated else (hole["x"], hole["y"])
            moved.append({"x": round(x + center[0] + long_axis[0] * offset, 3),
                          "y": round(y + center[1] + long_axis[1] * offset, 3), "d": hole["d"]})
        walls_b = [{"circle": (h["x"], h["y"], h["d"])} for h in moved]
        wall_ab = min([hole_wall(a, b) for a in holes_a for b in walls_b], default=None)
        if wall_ab is None or wall_ab >= MIN_WALL_MM:
            present = [w for w in (wall_aa, wall_ab, wall_bb) if w is not None]
            walls = {"aa": round(wall_aa, 3) if wall_aa is not None else None,
                     "ab": round(wall_ab, 3) if wall_ab is not None else None,
                     "bb": round(wall_bb, 3) if wall_bb is not None else None,
                     "min": round(min(present), 3) if present else None}
            return {"candidate": name, "holes_b": moved, "walls": walls}
    return None
