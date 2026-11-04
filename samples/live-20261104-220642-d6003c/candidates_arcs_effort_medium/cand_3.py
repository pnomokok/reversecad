import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner (53.3,-47.36) by ~8-10 mm (chamfer not in measured 4-point polygon); hole X positions by ~2.2 mm (measured top edge is slanted ~13 mm due to perspective/rotation vs clean rectangle)

def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    hole_diameter=6.0,
    hole_spacing_x=79.18,
    hole_spacing_y=75.5,
    chamfer_size=13.0,
):
    hl = length / 2.0
    hw = width / 2.0
    # rectangular outline with chamfer at +X -Y corner (bottom-right in image)
    pts = [
        (-hl, -hw),
        (-hl, hw),
        (hl, hw),
        (hl, -hw + chamfer_size),
        (hl - chamfer_size, -hw),
    ]
    part = pk.outline_from_points(pts, thickness)
    # 4 corner holes as symmetric pattern; margins stay symmetric when length/width change
    hole_pts = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, hole_pts, hole_diameter)
    return part
