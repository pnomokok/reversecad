import cadquery as cq
import partkit as pk
import math

def build_part(length=69.64, width=50.42, arm_width=19.92, thickness=3.0, hole_diameter=8.03, hole_edge_margin=12.0):
    # L-shape: full length top bar + left vertical stem
    # arm_width is width of both arms (averaged), notch = length-arm_width by width-arm_width
    half_l = length / 2.0
    half_w = width / 2.0
    inner_x = -half_l + arm_width
    inner_y = half_w - arm_width

    pts = [
        (-half_l, -half_w),
        (-half_l, half_w),
        (half_l, half_w),
        (half_l, inner_y),
        (inner_x, inner_y),
        (inner_x, -half_w),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered across arm, offset from outer ends by hole_edge_margin
    h1_x = -half_l + arm_width / 2.0
    h1_y = -half_w + hole_edge_margin
    h2_x = half_l - hole_edge_margin
    h2_y = half_w - arm_width / 2.0

    part = pk.cut_circle(part, (h1_x, h1_y), hole_diameter)
    part = pk.cut_circle(part, (h2_x, h2_y), hole_diameter)

    return part
