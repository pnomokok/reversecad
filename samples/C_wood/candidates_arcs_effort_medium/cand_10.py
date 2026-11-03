import cadquery as cq
import partkit as pk
import math

def build_part(length=69.64, width=50.42, arm_width=19.7, end_margin=12.0, hole_diameter=8.03, thickness=3.0):
    # clean L-shape: overall length x width, both legs with same width (arm_width)
    # notch inner corner derived from arm_width
    x_left = -length / 2.0
    x_right = length / 2.0
    y_bottom = -width / 2.0
    y_top = width / 2.0
    x_inner = x_left + arm_width
    y_inner = y_top - arm_width

    pts = [
        (x_left, y_bottom),
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_inner),
        (x_inner, y_inner),
        (x_inner, y_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered across arm width, offset from the outer ends by end_margin
    # left vertical leg hole (south end) and top horizontal leg hole (east end)
    hole1_center = (x_left + arm_width / 2.0, y_bottom + end_margin)
    hole2_center = (x_right - end_margin, y_top - arm_width / 2.0)

    part = pk.cut_circle(part, hole1_center, hole_diameter)
    part = pk.cut_circle(part, hole2_center, hole_diameter)

    return part
