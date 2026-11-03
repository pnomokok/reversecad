import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.54,
    width=37.25,
    thickness=3.0,
    main_width=25.17,
    tab_width=15.64,
    tab_length=12.08,
    small_hole_dia=6.03,
    large_hole_dia=10.04,
):
    # Derived geometry - keep design intent:
    # - main body is length x main_width rectangle
    # - tab is tab_width x tab_length rectangle centered on bottom edge of main body
    # - total width = main_width + tab_length, centered at origin
    # - holes are centered on their respective rectangles

    # bounding limits
    x_half = length / 2.0
    y_top = width / 2.0
    y_bottom = -width / 2.0
    y_main_bottom = y_bottom + tab_length
    x_tab_half = tab_width / 2.0

    # outline points in order (clockwise starting at tab bottom-left)
    pts = [
        (-x_tab_half, y_bottom),
        (-x_tab_half, y_main_bottom),
        (-x_half, y_main_bottom),
        (-x_half, y_top),
        (x_half, y_top),
        (x_half, y_main_bottom),
        (x_tab_half, y_main_bottom),
        (x_tab_half, y_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centers - centered on tab and on main body
    tab_center = (0.0, y_bottom + tab_length / 2.0)
    main_center = (0.0, tab_length / 2.0)

    part = pk.cut_circle(part, tab_center, small_hole_dia)
    part = pk.cut_circle(part, main_center, large_hole_dia)

    return part
