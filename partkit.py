"""Small, tested CadQuery helpers for candidate programs (import partkit as pk).

They avoid the CadQuery pitfalls seen in earlier candidates: all positions are
absolute (no cumulative .center()), outlines take the full corner list (no
moveTo + polyline dropping a point), and cutters reach past both faces. Every
function returns a new part; parts lie on the XY plane with the bottom at Z = 0.
Angles are in degrees from the +X axis.
"""
import math

import cadquery as cq

__all__ = [
    "plate", "outline_from_points", "symmetric_points", "grid_points", "hole_pattern", "cut_circle",
    "cut_rectangle", "cut_slot", "cut_ellipse", "cut_polygon", "semicircle_notch", "tab",
]


def _z_range(part):
    box = part.val().BoundingBox()
    return box.zmin, box.zmax


def _cutter(part, x, y, sketch):
    """A cutting solid at (x, y): `sketch` draws on a workplane there; it reaches 1 mm past both faces."""
    zmin, zmax = _z_range(part)
    return sketch(cq.Workplane("XY", origin=(x, y, zmin - 1))).extrude(zmax - zmin + 2)


def plate(length, width, thickness):
    """Rectangular plate centered on the origin: length along X, width along Y, bottom at Z = 0."""
    return cq.Workplane("XY").box(length, width, thickness, centered=(True, True, False))


def outline_from_points(points, thickness):
    """Extrude the closed outline through every (x, y) corner in order (the last joins the first)."""
    return cq.Workplane("XY").polyline([tuple(map(float, p)) for p in points]).close().extrude(thickness)


def symmetric_points(spacing_x, spacing_y=0.0, center=(0.0, 0.0)):
    """Points placed symmetrically about center: the corners of a spacing_x by spacing_y rectangle
    (2 points if one spacing is 0, 1 point if both are)."""
    xs = {-spacing_x / 2, spacing_x / 2}
    ys = {-spacing_y / 2, spacing_y / 2}
    return [(center[0] + x, center[1] + y) for x in sorted(xs) for y in sorted(ys)]


def grid_points(count_x, count_y, pitch_x, pitch_y, center=(0.0, 0.0)):
    """count_x by count_y points with the given pitches, centered on center."""
    return [(center[0] + (i - (count_x - 1) / 2) * pitch_x, center[1] + (j - (count_y - 1) / 2) * pitch_y)
            for i in range(count_x) for j in range(count_y)]


def cut_circle(part, center, diameter):
    """Cut a round through-hole of the given diameter at center (x, y)."""
    return part.cut(_cutter(part, *center, lambda w: w.circle(diameter / 2)))


def hole_pattern(part, points, diameter):
    """Cut round through-holes of one shared diameter at every (x, y) point."""
    for point in points:
        part = cut_circle(part, point, diameter)
    return part


def cut_rectangle(part, center, length, width, angle=0.0):
    """Cut a rectangular through-hole: length along `angle`, width across it."""
    return part.cut(_cutter(part, *center, lambda w: w.transformed(rotate=(0, 0, angle)).rect(length, width)))


def cut_slot(part, center, length, width, angle=0.0):
    """Cut a slot (semicircular ends): length is overall, end to end; width is the end diameter."""
    return part.cut(_cutter(part, *center, lambda w: w.transformed(rotate=(0, 0, angle)).slot2D(length, width)))


def cut_ellipse(part, center, length, width, angle=0.0):
    """Cut an elliptical through-hole: length and width are the full axes."""
    return part.cut(_cutter(part, *center,
                            lambda w: w.transformed(rotate=(0, 0, angle)).ellipse(length / 2, width / 2)))


def cut_polygon(part, points):
    """Cut a through-hole bounded by the (x, y) corners in order."""
    return part.cut(_cutter(part, 0.0, 0.0, lambda w: w.polyline([tuple(map(float, p)) for p in points]).close()))


def semicircle_notch(part, center, radius):
    """Cut a round notch into an edge: a circle of the given radius centered on the edge point (x, y)."""
    return cut_circle(part, center, 2 * radius)


def tab(part, base_center, length, width, angle):
    """Add a rectangular tab: its base is centered on base_center (a point on the outline edge) and it
    sticks out `length` in direction `angle` (0 = +X, 90 = +Y); `width` is measured across."""
    zmin, zmax = _z_range(part)
    overlap = 0.01  # reach slightly into the part so the union fuses
    direction = (math.cos(math.radians(angle)), math.sin(math.radians(angle)))
    reach = length + overlap
    cx = base_center[0] + direction[0] * (length - overlap) / 2
    cy = base_center[1] + direction[1] * (length - overlap) / 2
    block = (cq.Workplane("XY", origin=(cx, cy, zmin)).transformed(rotate=(0, 0, angle))
             .rect(reach, width).extrude(zmax - zmin))
    return part.union(block)
