import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.02, hole_spacing_x=63.32, hole_spacing_y=24.27):
    part = pk.plate(length, width, thickness)
    points = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
