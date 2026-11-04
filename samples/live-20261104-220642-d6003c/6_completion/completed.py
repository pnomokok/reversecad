import cadquery as cq
import partkit as pk
import math


def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    chamfer_size=13.0,
    hole_diameter=6.0,
    top_left_inset=(11.54, 9.75),
    bottom_left_inset=(12.84, 10.18),
    top_right_inset=(15.74, 11.48),
    bottom_right_inset=(14.72, 10.68),
    restored_corner_leg=13.0,
):
    hl = length / 2.0
    hw = width / 2.0

    # Measured plate, restored to the full rectangle when
    # restored_corner_leg is present: the straight top/right and
    # bottom/left plate edges are extended to their intersection
    # at (+hl, -hw), restoring the triangular broken corner whose
    # leg is chamfer_size/restored_corner_leg.
    if restored_corner_leg > 0:
        pts = [
            (-hl, -hw),
            (-hl, hw),
            (hl, hw),
            (hl, -hw),
        ]
    else:
        pts = [
            (-hl, -hw),
            (-hl, hw),
            (hl, hw),
            (hl, -hw + chamfer_size),
            (hl - chamfer_size, -hw),
        ]
    part = pk.outline_from_points(pts, thickness)

    # Each hole is anchored to its nearest corner by its measured edge
    # insets, so the holes move with the plate edges if length/width change.
    hole_pts = [
        (-hl + top_left_inset[0], hw - top_left_inset[1]),
        (-hl + bottom_left_inset[0], -hw + bottom_left_inset[1]),
        (hl - top_right_inset[0], hw - top_right_inset[1]),
        (hl - bottom_right_inset[0], -hw + bottom_right_inset[1]),
    ]
    part = pk.hole_pattern(part, hole_pts, hole_diameter)

    return part
