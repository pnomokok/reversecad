import cadquery as cq
import partkit as pk
import math

def build_part(
    overall_length=69.64,
    overall_width=50.42,
    vertical_arm_width=19.7,
    top_arm_height=20.37,
    hole_diameter=8.03,
    hole_margin=12.0,
    thickness=3.0,
):
    # bounding box centered at origin
    x_min = -overall_length / 2.0
    x_max = overall_length / 2.0
    y_min = -overall_width / 2.0
    y_max = overall_width / 2.0

    # inner step corner of the L
    x_mid = x_min + vertical_arm_width
    y_mid = y_max - top_arm_height

    pts = [
        (x_min, y_min),
        (x_min, y_max),
        (x_max, y_max),
        (x_max, y_mid),
        (x_mid, y_mid),
        (x_mid, y_min),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered across arm width, inset from arm ends by hole_margin
    # hole in vertical (left) arm
    hx1 = x_min + vertical_arm_width / 2.0
    hy1 = y_min + hole_margin
    # hole in horizontal (top) arm
    hx2 = x_max - hole_margin
    hy2 = y_max - top_arm_height / 2.0

    part = pk.cut_circle(part, (hx1, hy1), hole_diameter)
    part = pk.cut_circle(part, (hx2, hy2), hole_diameter)

    return part
