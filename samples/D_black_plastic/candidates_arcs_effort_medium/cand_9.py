import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.5,
    main_width=25.0,
    tab_width=16.0,
    tab_height=12.0,
    thickness=3.0,
    tab_hole_dia=6.0,
    main_hole_dia=10.0,
):
    # Overall bounding size is length x (main_width+tab_height)
    # Main plate center is at y = tab_height/2 to keep bounding center at origin
    half_L = length / 2.0
    half_tab = tab_width / 2.0
    y_main = tab_height / 2.0
    y_top = y_main + main_width / 2.0          # overall max Y
    y_bottom_main = y_main - main_width / 2.0  # junction line
    y_tip = y_bottom_main - tab_height         # overall min Y = -y_top

    pts = [
        (-half_tab, y_tip),
        (-half_tab, y_bottom_main),
        (-half_L, y_bottom_main),
        (-half_L, y_top),
        (half_L, y_top),
        (half_L, y_bottom_main),
        (half_tab, y_bottom_main),
        (half_tab, y_tip),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered on main body and on tab
    main_center = (0.0, y_main)
    tab_center = (0.0, -main_width / 2.0)

    part = pk.cut_circle(part, main_center, main_hole_dia)
    part = pk.cut_circle(part, tab_center, tab_hole_dia)

    return part
