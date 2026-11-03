import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.64,
    width=50.42,
    arm_width=20.0,
    thickness=3.0,
    hole_diameter=8.03,
    hole_margin=12.0,
):
    half_L = length / 2.0
    half_W = width / 2.0

    # L-shape with corner at top-left: full length on top, full width on left
    # arm_width is the thickness of both arms (averaged from 19.5 and 20.3)
    p0 = (-half_L, -half_W)
    p1 = (-half_L, half_W)
    p2 = (half_L, half_W)
    p3 = (half_L, half_W - arm_width)
    p4 = (-half_L + arm_width, half_W - arm_width)
    p5 = (-half_L + arm_width, -half_W)

    points = [p0, p1, p2, p3, p4, p5]

    part = pk.outline_from_points(points, thickness)

    # holes centered across arm width, set back from arm ends by hole_margin
    hole_left = (-half_L + arm_width / 2.0, -half_W + hole_margin)
    hole_top = (half_L - hole_margin, half_W - arm_width / 2.0)

    part = pk.hole_pattern(part, [hole_left, hole_top], hole_diameter)

    return part
