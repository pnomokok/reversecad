import cadquery as cq
import partkit as pk
import math

def build_part(length=79.31, width=40.26, thickness=3.0, hole_diameter=6.0, margin_x=8.0, margin_y=8.0):
    # Base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Hole pattern: 4 corners, symmetric about center
    # spacing derived from edge margins so changing length/width keeps margin
    spacing_x = length - 2 * margin_x
    spacing_y = width - 2 * margin_y
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)

    return part
