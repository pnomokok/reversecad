import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner (51.68, 35.26) by ~13 mm vs clean rectangular corner (53.3, 48.27)
# the measured 4-point polygon omits the chamfer detail; the clean design intent
# is a rectangular plate with one chamfered corner, as shown in the silhouette.

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
):
    hl = length / 2.0
    hw = width / 2.0

    # Rectangular plate with a 45-degree chamfer at the +X, -Y corner.
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
    # The insets differ by more than 0.5 mm, so a single symmetric spacing
    # cannot reproduce the measured centres.
    hole_pts = [
        (-hl + top_left_inset[0], hw - top_left_inset[1]),
        (-hl + bottom_left_inset[0], -hw + bottom_left_inset[1]),
        (hl - top_right_inset[0], hw - top_right_inset[1]),
        (hl - bottom_right_inset[0], -hw + bottom_right_inset[1]),
    ]
    part = pk.hole_pattern(part, hole_pts, hole_diameter)

    return part
