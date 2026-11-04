import cadquery as cq
import partkit as pk
import math

def build_part(length=104.0, width=98.0, margin=6.75, dia_a=6.0, dia_b=5.5, thickness=3.0):
    part = pk.plate(length, width, thickness)
    pts_a = [(38.58, -37.59), (-40.46, -38.09), (37.56, 36.78), (-41.76, 38.52)]
    pts_b = [(-31.52, -0.09), (28.48, -0.09)]
    part = pk.hole_pattern(part, pts_a, dia_a)
    part = pk.hole_pattern(part, pts_b, dia_b)
    return part
