import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner (51.68, 35.26) by ~13.1 mm vs clean rectangular corner (53.3, 48.27)
# the measured 4-point trapezoid is the nearest fit to a rectangle with a bottom-right chamfer;
# the clean design intent is a rectangular plate with a chamfered corner, hole pattern symmetric.

def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    chamfer_size=14.0,
    hole_diameter=6.0,
    hole_spacing_x=79.18,
    hole_spacing_y=75.5,
):
    # chamfer at bottom-right (X=+length/2, Y=-width/2) to match image
    # 5-point outline: rectangle with one corner cut off
    pts = [
        (-length / 2, -width / 2),
        (-length / 2,  width / 2),
        ( length / 2,  width / 2),
        ( length / 2, -width / 2 + chamfer_size),
        ( length / 2 - chamfer_size, -width / 2),
    ]
    part = pk.outline_from_points(pts, thickness)

    # symmetric 4-hole pattern at corners, shared diameter
    points = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)

    return part
