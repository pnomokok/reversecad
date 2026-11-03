import cadquery as cq
import partkit as pk
import math

def build_part(
    overall_length=49.54,
    overall_width=37.25,
    tab_width=15.7,
    tab_length=12.05,
    small_hole_diameter=6.03,
    large_hole_diameter=10.04,
    thickness=3.0,
):
    # Derived geometry to keep symmetry
    # Bounding rectangle centered at origin: X = u, Y = v
    # Main body is on top, tab protrudes to -Y
    half_L = overall_length / 2.0
    half_W = overall_width / 2.0
    half_tw = tab_width / 2.0
    shoulder_y = -half_W + tab_length  # Y of main bottom / tab top
    top_y = half_W
    bottom_y = -half_W

    # Outline in clockwise order starting at tab bottom left
    pts = [
        (-half_tw, bottom_y),
        (-half_tw, shoulder_y),
        (-half_L, shoulder_y),
        (-half_L, top_y),
        (half_L, top_y),
        (half_L, shoulder_y),
        (half_tw, shoulder_y),
        (half_tw, bottom_y),
    ]

    part = pk.outline_from_points(pts, thickness)

    # Hole centers: centered in X, centered in their respective rectangles
    # Tab hole centered in tab, main hole centered in main body
    tab_center_y = -half_W + tab_length / 2.0
    main_center_y = (top_y + shoulder_y) / 2.0  # = tab_length/2 in this coordinate system

    part = pk.cut_circle(part, (0.0, tab_center_y), small_hole_diameter)
    part = pk.cut_circle(part, (0.0, main_center_y), large_hole_diameter)

    return part
