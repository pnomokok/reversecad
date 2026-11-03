import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.02, hole_margin=8.0):
    # Base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)
    # Hole pattern: 4 holes at corners, symmetric about center
    # spacing derived from overall size and edge margin to keep symmetry
    # when length/width change
    spacing_x = length - 2 * hole_margin
    spacing_y = width - 2 * hole_margin
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
