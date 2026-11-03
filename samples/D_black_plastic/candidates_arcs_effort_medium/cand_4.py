import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.54,
    width=37.25,
    tab_width=15.65,
    tab_protrusion=12.09,
    small_hole_dia=6.03,
    large_hole_dia=10.04,
    thickness=3.0,
):
    # Overall bounding box centered at origin: X in [-length/2, length/2], Y in [-width/2, width/2]
    # T-shape: main rectangular body on top + central tab protruding -Y
    # Derived from measurements: tab centered on X, protruding from main body bottom edge
    half_len = length / 2.0
    half_wid = width / 2.0
    half_tab = tab_width / 2.0
    y_main_bottom = -half_wid + tab_protrusion  # bottom edge of main body / top edge of tab
    y_top = half_wid
    y_bottom = -half_wid

    pts = [
        (-half_tab, y_bottom),
        (-half_tab, y_main_bottom),
        (-half_len, y_main_bottom),
        (-half_len, y_top),
        (half_len, y_top),
        (half_len, y_main_bottom),
        (half_tab, y_main_bottom),
        (half_tab, y_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered in tab and in main body (symmetric in X, centered in Y of each rectangle)
    small_cy = -half_wid + tab_protrusion / 2.0
    large_cy = tab_protrusion / 2.0  # = (y_top + y_main_bottom)/2

    part = pk.cut_circle(part, (0.0, small_cy), small_hole_dia)
    part = pk.cut_circle(part, (0.0, large_cy), large_hole_dia)

    return part
