import cadquery as cq
import partkit as pk
import math

def build_part(length=79.31, width=40.26, thickness=3.0, hole_diameter=6.03, hole_margin=8.0):
    # base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # 4 corner holes symmetric about center, inset from edges by hole_margin
    # spacing keeps symmetry when length/width changes
    spacing_x = length - 2 * hole_margin
    spacing_y = width - 2 * hole_margin
    pts = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, pts, hole_diameter)

    return part
