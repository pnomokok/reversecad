import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.0, margin=8.0):
    # Base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)
    # Four corner holes symmetric about center, inset by margin from each edge
    spacing_x = length - 2.0 * margin
    spacing_y = width - 2.0 * margin
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
