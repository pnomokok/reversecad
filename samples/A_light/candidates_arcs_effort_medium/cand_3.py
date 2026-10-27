import cadquery as cq
import partkit as pk
import math

def build_part(
    length=79.31,
    width=40.26,
    thickness=3.0,
    hole_diameter=6.03,
    hole_spacing_x=63.3,
    hole_spacing_y=24.3,
):
    # Base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Four identical corner holes symmetric about center
    pts = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, pts, hole_diameter)

    return part
