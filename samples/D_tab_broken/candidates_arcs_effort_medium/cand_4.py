import cadquery as cq
import partkit as pk
import math

def build_part(length=49.52, width=27.37, tab_width=16.02, tab_length=2.15, hole_diameter=10.05, thickness=3.0, hole_x=-0.06, hole_y=1.06):
    # total width includes tab; main plate width is width - tab_length
    plate_width = width - tab_length
    y_top = width / 2.0
    y_bottom_main = y_top - plate_width
    y_bottom_tab = -width / 2.0
    x_left = -length / 2.0
    x_right = length / 2.0
    xt = tab_width / 2.0

    # 8-point outline: top edge, right side, tab, left side (centered on bounding box)
    pts = [
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_bottom_main),
        (xt, y_bottom_main),
        (xt, y_bottom_tab),
        (-xt, y_bottom_tab),
        (-xt, y_bottom_main),
        (x_left, y_bottom_main),
    ]

    part = pk.outline_from_points(pts, thickness)
    # single central hole, position relative to bounding-box center
    part = pk.cut_circle(part, (hole_x, hole_y), hole_diameter)
    return part
