import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.64,
    width=50.42,
    thickness=3.0,
    vertical_bar_width=19.7,
    horizontal_bar_height=20.2,
    hole_diameter=8.03,
    edge_margin=12.0,
):
    # overall bounding half sizes
    hx = length / 2.0
    hy = width / 2.0

    # inner notch corner
    # outline order matches measured polygon (clockwise, interior = L on top/left)
    # A bottom-left, B top-left, C top-right, D inner-right, E inner-corner, F inner-bottom
    x_left = -hx
    x_inner = -hx + vertical_bar_width
    x_right = hx

    y_bottom = -hy
    y_top = hy
    y_inner = y_top - horizontal_bar_height

    points = [
        (x_left, y_bottom),
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_inner),
        (x_inner, y_inner),
        (x_inner, y_bottom),
    ]

    part = pk.outline_from_points(points, thickness)

    # hole positions - centered in bar thickness, edge_margin from outer edge
    # hole1 in vertical leg (left side), margin from bottom edge
    # hole2 in horizontal top bar, margin from right edge
    hole1_center = ( -hx + vertical_bar_width / 2.0, -hy + edge_margin )
    hole2_center = ( hx - edge_margin, y_top - horizontal_bar_height / 2.0 )

    part = pk.cut_circle(part, hole1_center, hole_diameter)
    part = pk.cut_circle(part, hole2_center, hole_diameter)

    return part
