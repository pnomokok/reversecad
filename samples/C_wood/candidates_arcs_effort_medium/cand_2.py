import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.64,
    width=50.42,
    arm_width=19.6,
    arm_height=20.32,
    thickness=3.0,
    hole_diameter=8.03,
    hole1_x=-25.0,
    hole1_y=-13.29,
    hole2_x=22.73,
    hole2_y=14.87,
):
    # L-shape: full bounding rectangle length x width,
    # vertical arm on the left (width = arm_width) spanning full height,
    # horizontal arm on the top (height = arm_height) spanning full length.
    # Inner corner is at (x_left+arm_width, y_top-arm_height)
    x_left = -length / 2.0
    x_right = length / 2.0
    y_bottom = -width / 2.0
    y_top = width / 2.0
    x_inner = x_left + arm_width
    y_inner = y_top - arm_height

    pts = [
        (x_left, y_bottom),
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_inner),
        (x_inner, y_inner),
        (x_inner, y_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # two through holes, same nominal diameter
    part = pk.cut_circle(part, (hole1_x, hole1_y), hole_diameter)
    part = pk.cut_circle(part, (hole2_x, hole2_y), hole_diameter)

    return part
