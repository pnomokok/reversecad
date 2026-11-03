import cadquery as cq
import partkit as pk
import math

def build_part(length=79.34, width=40.26, thickness=3.0, hole_diameter=6.02, edge_margin=8.0):
    # Base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)
    # Symmetric 4-hole pattern: distance to edge kept constant so pattern scales with plate size
    spacing_x = length - 2 * edge_margin
    spacing_y = width - 2 * edge_margin
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
