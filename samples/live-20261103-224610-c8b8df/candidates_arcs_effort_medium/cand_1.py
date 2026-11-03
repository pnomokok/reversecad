import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner (51.68, 35.26) by ~13 mm and hole x positions by ~2.2 mm vs symmetric intent; nearest clean rectangular intent used
def build_part(length=106.6, width=96.53, thickness=3.0, chamfer_size=12.0, hole_diameter=6.0, margin_x=13.71, margin_y=10.52):
    sx = length - 2 * margin_x
    sy = width - 2 * margin_y
    lx = length / 2
    wy = width / 2
    c = chamfer_size
    # rectangular outline with 45deg chamfer at +X -Y corner (bottom-right)
    pts = [
        (-lx, -wy),
        (lx - c, -wy),
        (lx, -wy + c),
        (lx, wy),
        (-lx, wy),
    ]
    part = pk.outline_from_points(pts, thickness)
    # four corner holes symmetric about center
    hole_pts = pk.symmetric_points(sx, sy, center=(0.0, 0.0))
    part = pk.hole_pattern(part, hole_pts, hole_diameter)
    return part
