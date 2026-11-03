import cadquery as cq
import partkit as pk
import math

def build_part(
    main_length=49.5,
    main_width=25.2,
    tab_width=15.6,
    tab_length=12.0,
    main_hole_dia=10.0,
    tab_hole_dia=6.0,
    thickness=3.0
):
    total_width = main_width + tab_length
    y_top = total_width / 2
    y_bottom_main = y_top - main_width
    y_bottom = -total_width / 2

    half_main = main_length / 2
    half_tab = tab_width / 2

    # outline points in order (CCW) centered on bounding-box origin
    pts = [
        (-half_tab, y_bottom),        # tab bottom left
        (-half_tab, y_bottom_main),   # tab top left
        (-half_main, y_bottom_main),  # main bottom left
        (-half_main, y_top),          # main top left
        (half_main, y_top),           # main top right
        (half_main, y_bottom_main),   # main bottom right
        (half_tab, y_bottom_main),    # tab top right
        (half_tab, y_bottom),         # tab bottom right
    ]

    part = pk.outline_from_points(pts, thickness)

    # main plate hole - centered in main rectangle
    main_center = (0.0, y_bottom_main + main_width / 2)
    part = pk.cut_circle(part, main_center, main_hole_dia)

    # tab hole - centered in tab
    tab_center = (0.0, y_bottom + tab_length / 2)
    part = pk.cut_circle(part, tab_center, tab_hole_dia)

    return part
