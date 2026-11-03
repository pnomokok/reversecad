import cadquery as cq
import partkit as pk
import math

# exceeds: outline corner at index 2 (top-right y) by ~13mm due to perspective skew - replaced by clean rectangle
# exceeds: outline bottom-right corner by ~10-15mm due to chamfer not captured as polygon vertex
# exceeds: hole x positions by ~1.5mm from symmetric average (perspective asymmetry) - replaced by symmetric pattern

def build_part(length=106.6, width=96.53, thickness=3.0, chamfer_size=15.0, hole_diameter=6.0, hole_pitch_x=79.2, hole_pitch_y=75.5):
    # base rectangle with chamfer at bottom-right (+X, -Y) corner
    # chamfer_size is the equal cut along X and Y from the corner
    half_l = length / 2.0
    half_w = width / 2.0
    pts = [
        (-half_l, -half_w),
        (-half_l, half_w),
        (half_l, half_w),
        (half_l, -half_w + chamfer_size),
        (half_l - chamfer_size, -half_w),
    ]
    part = pk.outline_from_points(pts, thickness)
    # symmetric 2x2 hole pattern centered on part
    points = pk.symmetric_points(hole_pitch_x, hole_pitch_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
