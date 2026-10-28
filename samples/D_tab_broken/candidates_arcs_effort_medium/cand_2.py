import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.52,
    width=25.14,
    thickness=3.0,
    tab_length=17.08,
    tab_protrusion=2.23,
    hole_diameter=10.05,
    hole_x=-0.06,
    hole_y=1.06,
):
    # overall size includes tab; origin is centre of bounding rectangle
    overall_width = width + tab_protrusion
    half_len = length / 2.0
    half_overall = overall_width / 2.0
    # bottom of main rectangle (top of tab)
    main_bottom = half_overall - width  # = -width/2 + tab_protrusion/2

    # clean rectangular outline with centered tab on -Y side
    # clockwise from top-right
    pts = [
        (half_len, half_overall),
        (-half_len, half_overall),
        (-half_len, main_bottom),
        (-tab_length / 2.0, main_bottom),
        (-tab_length / 2.0, -half_overall),
        (tab_length / 2.0, -half_overall),
        (tab_length / 2.0, main_bottom),
        (half_len, main_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)
    part = pk.cut_circle(part, (hole_x, hole_y), hole_diameter)
    return part
