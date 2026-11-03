import cadquery as cq
import partkit as pk
import math

def build_part(length=69.64, width=50.42, arm_thickness=20.0, hole_diameter=8.03, hole_margin=12.0, thickness=3.0):
    # Overall bounding size
    x_left = -length / 2.0
    x_right = length / 2.0
    y_bottom = -width / 2.0
    y_top = width / 2.0

    # L-shape: left vertical bar (full height) + top horizontal bar
    # inner corner is offset by arm_thickness from left and top
    x_inner = x_left + arm_thickness
    y_inner = y_top - arm_thickness

    pts = [
        (x_left, y_bottom),
        (x_left, y_top),
        (x_right, y_top),
        (x_right, y_inner),
        (x_inner, y_inner),
        (x_inner, y_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # holes centered across the arm thickness, offset hole_margin from the far ends
    # vertical arm hole: centered in x, margin from bottom
    h1_x = x_left + arm_thickness / 2.0
    h1_y = y_bottom + hole_margin
    # top arm hole: centered in y, margin from right
    h2_x = x_right - hole_margin
    h2_y = y_top - arm_thickness / 2.0

    part = pk.cut_circle(part, (h1_x, h1_y), hole_diameter)
    part = pk.cut_circle(part, (h2_x, h2_y), hole_diameter)

    return part
