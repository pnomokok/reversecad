import cadquery as cq
import partkit as pk
import math

# exceeds: bottom-right chamfer (~12mm cut) not in 4-corner measurement - corner distance >2% ; hole positions up to ~2.2mm asymmetry from perspective - using symmetric intent exceeds 0.5mm
def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    hole_diameter=6.0,
    hole_spacing_x=79.2,
    hole_spacing_y=75.5,
    chamfer_x=12.0,
    chamfer_y=12.0,
):
    # outline with chamfer at bottom-right (+X, -Y) corner
    half_l = length / 2.0
    half_w = width / 2.0
    pts = [
        (-half_l, -half_w),
        (half_l - chamfer_x, -half_w),
        (half_l, -half_w + chamfer_y),
        (half_l, half_w),
        (-half_l, half_w),
    ]
    part = pk.outline_from_points(pts, thickness)

    # 4 holes in rectangular symmetric pattern centered on part
    points = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)

    return part
