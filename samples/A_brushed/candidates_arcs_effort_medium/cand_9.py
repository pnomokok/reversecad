import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.0, hole_margin_x=8.0, hole_margin_y=8.0):
    # Base plate - rectangular outline centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Four corner holes in a symmetric rectangular pattern
    # Spacing derived from edge margins so symmetry is kept if length/width change
    spacing_x = length - 2 * hole_margin_x
    spacing_y = width - 2 * hole_margin_y
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))

    part = pk.hole_pattern(part, points, hole_diameter)
    return part
