import cadquery as cq
import partkit as pk
import math

def build_part(length=49.5, width=37.2, tab_width=15.7, tab_length=12.0, thickness=3.0, tab_hole_dia=6.0, main_hole_dia=10.0):
    # derived sizes
    main_width = width - tab_length
    half_len = length / 2.0
    half_wid = width / 2.0
    y_main_bottom = half_wid - main_width  # = -half_wid + tab_length
    y_tab_bottom = -half_wid
    half_tab = tab_width / 2.0

    # outline points (counter-clockwise) centered at bounding-box center
    pts = [
        (-half_tab, y_tab_bottom),
        (-half_tab, y_main_bottom),
        (-half_len, y_main_bottom),
        (-half_len, half_wid),
        (half_len, half_wid),
        (half_len, y_main_bottom),
        (half_tab, y_main_bottom),
        (half_tab, y_tab_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centers: centered in tab and in main plate
    tab_hole_center = (0.0, y_tab_bottom + tab_length / 2.0)
    main_hole_center = (0.0, half_wid - main_width / 2.0)

    part = pk.cut_circle(part, tab_hole_center, tab_hole_dia)
    part = pk.cut_circle(part, main_hole_center, main_hole_dia)

    return part
