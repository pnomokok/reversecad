import cadquery as cq
import partkit as pk
import math

def build_part(length=79.31, width=40.26, thickness=3.0, hole_diameter=6.0, edge_margin=8.0):
    # Base rectangular plate
    part = pk.plate(length, width, thickness)
    # Hole pattern inset from edges by edge_margin, symmetric about center
    spacing_x = length - 2 * edge_margin
    spacing_y = width - 2 * edge_margin
    pts = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, pts, hole_diameter)
    return part
