import cadquery as cq
import partkit as pk
import math

def build_part(length=103.02, width=96.54, margin=6.75, dia_a=6.0, dia_b=5.5, thickness=3.0):
    # Plate centered on origin; length/width chosen so every hole edge is >= margin from outline
    # Required half-length = max(|x|+r)+margin = 44.76+6.75 = 51.51 -> length 103.02
    # Required half-width  = max(|y|+r)+margin = 41.52+6.75 = 48.27 -> width 96.54
    # Symmetry center of both patterns is approx (-1.52, -0.09), plate at origin encloses it with margin
    part = pk.plate(length, width, thickness)

    # Pattern A - 4 holes, diameter dia_a, absolute positions
    pts_a = [
        (38.58, -37.59),
        (-40.46, -38.09),
        (37.56, 36.78),
        (-41.76, 38.52),
    ]
    part = pk.hole_pattern(part, pts_a, dia_a)

    # Pattern B - 2 holes, diameter dia_b, absolute positions
    pts_b = [
        (-31.52, -0.09),
        (28.48, -0.09),
    ]
    part = pk.hole_pattern(part, pts_b, dia_b)

    return part
