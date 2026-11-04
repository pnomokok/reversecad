import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner at bottom-right chamfer deviates >2% due to chamfer not in measured polygon; hole positions exceed 0.5mm due to perspective distortion in measured centers (symmetrized)
def build_part(length=106.6, width=96.53, thickness=3.0, chamfer=15.0, hole_diameter=6.0, margin_x=12.0, margin_y=10.0):
    # clean rectangular intent with single chamfer at bottom-right (+X, -Y) corner
    x0 = length / 2
    y0 = width / 2
    c = chamfer
    # outline counter-clockwise starting at bottom-left
    pts = [
        (-x0, -y0),
        (-x0,  y0),
        ( x0,  y0),
        ( x0, -y0 + c),
        ( x0 - c, -y0),
    ]
    part = pk.outline_from_points(pts, thickness)

    # four corner holes symmetric about center, driven by edge margins
    sx = length - 2 * margin_x
    sy = width - 2 * margin_y
    points = pk.symmetric_points(sx, sy)
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
