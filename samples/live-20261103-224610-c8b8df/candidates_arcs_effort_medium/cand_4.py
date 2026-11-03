import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner distance by ~5.7 mm (measured corner (53.3,-47.36) is 7.8 mm from chamfer edge) and hole position by ~1.7 mm in X due to perspective asymmetry - clean rectangular chamfer and symmetric hole pattern chosen per image
def build_part(length=106.6, width=96.53, thickness=3.0, hole_diameter=6.0, margin_x=13.71, margin_y=10.52, chamfer=12.0):
    # chamfered rectangle: one 45 deg chamfer at +X -Y corner
    lx = length / 2.0
    wy = width / 2.0
    c = chamfer
    # points CCW starting at -X -Y
    pts = [
        (-lx, -wy),
        (-lx, wy),
        (lx, wy),
        (lx, -wy + c),
        (lx - c, -wy),
    ]
    part = pk.outline_from_points(pts, thickness)

    # symmetric 4-hole pattern near corners, inset by margins
    spacing_x = length - 2.0 * margin_x
    spacing_y = width - 2.0 * margin_y
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)

    return part
