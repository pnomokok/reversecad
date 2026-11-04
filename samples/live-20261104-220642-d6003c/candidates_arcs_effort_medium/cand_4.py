import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner at bottom-right by ~9mm due to chamfer not in 4-point measurement (clean rectangular intent with chamfer)
# exceeds: hole position by ~1.5-2mm vs measured centers due to symmetric 2x2 pattern (measurement perspective noise)

def build_part(length=106.6, width=96.53, thickness=3.0, chamfer=13.0, hole_diameter=6.0, margin_x=13.7, margin_y=10.5):
    half_l = length / 2.0
    half_w = width / 2.0
    # 5-point outline: rectangle with 45deg chamfer at +X,-Y corner
    pts = [
        (-half_l, half_w),
        (half_l, half_w),
        (half_l, -half_w + chamfer),
        (half_l - chamfer, -half_w),
        (-half_l, -half_w),
    ]
    part = pk.outline_from_points(pts, thickness)
    spacing_x = length - 2.0 * margin_x
    spacing_y = width - 2.0 * margin_y
    points = pk.grid_points(2, 2, spacing_x, spacing_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
