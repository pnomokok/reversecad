import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.54,
    width=37.25,
    thickness=3.0,
    tab_width=15.6,
    tab_protrusion=12.09,
    small_hole_dia=6.03,
    large_hole_dia=10.04,
):
    # derived geometry - keep symmetry and edge distances
    half_len = length / 2.0
    half_wid = width / 2.0
    y_tab_bottom = -half_wid
    y_tab_top = -half_wid + tab_protrusion  # also bottom of main body
    y_main_top = half_wid
    half_tab = tab_width / 2.0

    # outline: main rectangle + centered tab on the -Y side
    pts = [
        (-half_tab, y_tab_bottom),
        (-half_tab, y_tab_top),
        (-half_len, y_tab_top),
        (-half_len, y_main_top),
        (half_len, y_main_top),
        (half_len, y_tab_top),
        (half_tab, y_tab_top),
        (half_tab, y_tab_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered in their respective bodies
    small_hole_center = (0.0, y_tab_bottom + tab_protrusion / 2.0)
    large_hole_center = (0.0, (y_tab_top + y_main_top) / 2.0)

    part = pk.cut_circle(part, small_hole_center, small_hole_dia)
    part = pk.cut_circle(part, large_hole_center, large_hole_dia)

    return part
