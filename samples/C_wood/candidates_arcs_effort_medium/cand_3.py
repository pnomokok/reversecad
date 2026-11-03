import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.64,
    width=50.42,
    vertical_arm_width=19.52,
    top_arm_height=20.31,
    hole_diameter=8.03,
    hole_margin=12.0,
    thickness=3.0
):
    # Overall bounding box centered at origin: length along X, width along Y
    # L-shape: full top bar and full left bar, notch at bottom-right
    # vertical_arm_width = width of left arm (X)
    # top_arm_height = height of top bar (Y)
    half_L = length / 2.0
    half_W = width / 2.0

    # inner corner
    inner_x = -half_L + vertical_arm_width
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

    # holes centered in each arm, at hole_margin from the tip
    # hole in left vertical arm: centered in X, margin from bottom edge
    hole1_x = -half_L + vertical_arm_width / 2.0
    hole1_y = -half_W + hole_margin

    # hole in top horizontal arm: centered in Y, margin from right edge
    hole2_x = half_L - hole_margin
    hole2_y = half_W - top_arm_height / 2.0

    part = pk.cut_circle(part, (hole1_x, hole1_y), hole_diameter)
    part = pk.cut_circle(part, (hole2_x, hole2_y), hole_diameter)

    return part
