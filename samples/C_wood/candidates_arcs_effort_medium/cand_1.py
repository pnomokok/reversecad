import cadquery as cq
import partkit as pk
import math

def build_part(length=69.64, width=50.42, thickness=3.0, vert_arm_width=19.52, top_arm_height=20.32, hole_diameter=8.03, end_margin=12.0):
    half_L = length / 2.0
    half_W = width / 2.0
    inner_x = -half_L + vert_arm_width
    inner_y = half_W - top_arm_height

    points = [
        (-half_L, -half_W),
        (-half_L, half_W),
        (half_L, half_W),
        (half_L, inner_y),
        (inner_x, inner_y),
        (inner_x, -half_W),
    ]

    part = pk.outline_from_points(points, thickness)

    # holes centered across arm thickness, offset from arm ends by end_margin
    hole1_x = -half_L + vert_arm_width / 2.0
    hole1_y = -half_W + end_margin
    hole2_x = half_L - end_margin
    hole2_y = half_W - top_arm_height / 2.0

    part = pk.cut_circle(part, (hole1_x, hole1_y), hole_diameter)
    part = pk.cut_circle(part, (hole2_x, hole2_y), hole_diameter)

    return part
