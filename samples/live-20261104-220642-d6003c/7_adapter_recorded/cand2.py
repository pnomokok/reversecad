import cadquery as cq
import partkit as pk
import math

def build_part(length=103.02, width=96.54, thickness=3.0, margin=6.75, dia_a=6.0, dia_b=5.5):
    # base plate - rectangular, centered on origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Pattern A - 4 holes dia 6.0
    pts_a = [
        (38.58, -37.59),
        (-40.46, -38.09),
        (37.56, 36.78),
        (-41.76, 38.52),
    ]
    part = pk.hole_pattern(part, pts_a, dia_a)

    # Pattern B - 2 holes dia 5.5
    pts_b = [
        (-31.52, -0.09),
        (28.48, -0.09),
    ]
    part = pk.hole_pattern(part, pts_b, dia_b)

    return part
