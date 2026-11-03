import cadquery as cq
import partkit as pk
import math

def build_part(
    overall_length=49.54,
    overall_width=37.25,
    thickness=3.0,
    tab_width=15.6,
    tab_length=12.1,
    small_hole_diameter=6.03,
    large_hole_diameter=10.04,
):
    # Derived main width to keep overall_width = main_width + tab_length
    main_width = overall_width - tab_length

    # Outline is built from overall dimensions and tab dimensions
    # so changing overall_length / overall_width keeps symmetry.
    # Origin is centre of bounding rectangle (u=0, v=0).
    half_len = overall_length / 2.0
    half_w = overall_width / 2.0
    half_tab = tab_width / 2.0
    # y of the shoulder where tab meets main rectangle
    shoulder_y = -half_w + tab_length

    points = [
        (-half_tab, -half_w),
        (-half_tab, shoulder_y),
        (-half_len, shoulder_y),
        (-half_len, half_w),
        (half_len, half_w),
        (half_len, shoulder_y),
        (half_tab, shoulder_y),
        (half_tab, -half_w),
    ]

    part = pk.outline_from_points(points, thickness)

    # Hole centres are symmetric centres of their features
    # tab centre
    small_hole_center = (0.0, -half_w + tab_length / 2.0)
    # main rectangle centre
    large_hole_center_y = shoulder_y + main_width / 2.0
    large_hole_center = (0.0, large_hole_center_y)

    part = pk.cut_circle(part, small_hole_center, small_hole_diameter)
    part = pk.cut_circle(part, large_hole_center, large_hole_diameter)

    return part
