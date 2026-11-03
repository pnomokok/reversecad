import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.0, hole_margin_x=8.0, hole_margin_y=8.0):
    # Rectangular plate, 4x equal holes symmetric about center
    # hole positions defined by edge margins so symmetry and edge distance are preserved
    part = pk.plate(length, width, thickness)
    spacing_x = length - 2 * hole_margin_x
    spacing_y = width - 2 * hole_margin_y
    pts = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, pts, hole_diameter)
    return part
