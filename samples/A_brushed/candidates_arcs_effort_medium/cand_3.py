import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.02, edge_margin=8.0):
    # Rectangular plate with 4 corner holes in symmetric pattern
    # hole spacing derived from overall size and edge margin to preserve symmetry
    spacing_x = length - 2 * edge_margin
    spacing_y = width - 2 * edge_margin

    part = pk.plate(length, width, thickness)
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
