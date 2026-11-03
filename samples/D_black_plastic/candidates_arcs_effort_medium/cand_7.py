import cadquery as cq
import partkit as pk
import math

def build_part(length=49.54, width=37.25, thickness=3.0, tab_width=15.64, tab_length=12.09, tab_hole_dia=6.03, main_hole_dia=10.04):
    half_len = length / 2.0
    half_w = width / 2.0
    half_tab = tab_width / 2.0
    shoulder_y = -half_w + tab_length

    # outline points in order (CCW) - T shape with tab on -Y side
    pts = [
        (-half_tab, -half_w),
        (-half_tab, shoulder_y),
        (-half_len, shoulder_y),
        (-half_len, half_w),
        (half_len, half_w),
        (half_len, shoulder_y),
        (half_tab, shoulder_y),
        (half_tab, -half_w),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centers: centered in tab and in main body
    tab_center_y = -half_w + tab_length / 2.0
    main_center_y = (shoulder_y + half_w) / 2.0

    part = pk.cut_circle(part, (0.0, tab_center_y), tab_hole_dia)
    part = pk.cut_circle(part, (0.0, main_center_y), main_hole_dia)

    return part
