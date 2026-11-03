import cadquery as cq
import partkit as pk
import math

def build_part(
    overall_length=49.54,
    overall_width=37.25,
    tab_width=15.57,
    tab_length=12.09,
    small_hole_diameter=6.03,
    large_hole_diameter=10.04,
    thickness=3.0
):
    # Derived geometry keeps symmetry when overall size changes
    hl = overall_length / 2.0
    hw = overall_width / 2.0
    tw2 = tab_width / 2.0
    # Y of the main-body bottom edge / tab top edge
    tab_top_y = -hw + tab_length

    # 8-point outline: main rectangle + centered tab on -Y side
    points = [
        (-tw2, -hw),          # tab bottom left
        (tw2, -hw),           # tab bottom right
        (tw2, tab_top_y),      # tab top right
        (hl, tab_top_y),       # main bottom right
        (hl, hw),              # main top right
        (-hl, hw),             # main top left
        (-hl, tab_top_y),      # main bottom left
        (-tw2, tab_top_y),     # tab top left
    ]

    part = pk.outline_from_points(points, thickness)

    # Hole centers: centered in tab and centered in main body
    tab_hole_center = (0.0, -hw + tab_length / 2.0)
    main_hole_center = (0.0, tab_length / 2.0)

    part = pk.cut_circle(part, tab_hole_center, small_hole_diameter)
    part = pk.cut_circle(part, main_hole_center, large_hole_diameter)

    return part
