import cadquery as cq
import partkit as pk
import math

def build_part(
    length=79.34,
    width=40.26,
    thickness=3.0,
    hole_diameter=6.02,
    hole_margin=8.0,
):
    """
    Flat rectangular plate with 4 corner holes.
    - length, width, thickness: overall plate size
    - hole_diameter: shared diameter for the 4 holes
    - hole_margin: distance from outer edge to hole center (both X and Y),
                   holes are placed symmetrically
    """
    # Base plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Symmetric 4-hole pattern near corners
    # spacing = overall - 2*margin so margin to edge is preserved if length/width change
    spacing_x = length - 2 * hole_margin
    spacing_y = width - 2 * hole_margin
    points = pk.symmetric_points(spacing_x, spacing_y, center=(0.0, 0.0))

    part = pk.hole_pattern(part, points, hole_diameter)

    return part
