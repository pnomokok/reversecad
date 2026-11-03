import cadquery as cq
import partkit as pk
import math

def build_part(length=69.64, width=50.42, thickness=3.0, stem_width=19.88, bar_height=20.31, hole_diameter=8.03, hole_margin=12.01):
    # L-shape: top bar spans full length, left stem spans full width
    xl = -length / 2.0
    xr = length / 2.0
    yb = -width / 2.0
    yt = width / 2.0

    x_inner = xl + stem_width
    y_inner = yt - bar_height

    # outline clockwise: bottom-left -> top-left -> top-right -> mid-right -> inner -> bottom-mid
    pts = [
        (xl, yb),
        (xl, yt),
        (xr, yt),
        (xr, y_inner),
        (x_inner, y_inner),
        (x_inner, yb),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered in each arm, offset from the free end by hole_margin
    # hole in left stem (centered in stem_width, margin from bottom)
    h1_x = xl + stem_width / 2.0
    h1_y = yb + hole_margin

    # hole in top bar (centered in bar_height, margin from right)
    h2_x = xr - hole_margin
    h2_y = yt - bar_height / 2.0

    part = pk.cut_circle(part, (h1_x, h1_y), hole_diameter)
    part = pk.cut_circle(part, (h2_x, h2_y), hole_diameter)

    return part
