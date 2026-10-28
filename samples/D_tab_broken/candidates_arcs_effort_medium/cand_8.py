import cadquery as cq
import partkit as pk
import math

def build_part(length=49.52, width=25.15, tab_width=15.0, tab_protrusion=2.22, hole_diameter=10.05, thickness=3.0):
    # total bounding size (matches measured outline length/width)
    total_width = width + tab_protrusion
    # y coordinates with origin at bounding-box center (u,v origin)
    y_top = total_width / 2.0
    y_main_bottom = -total_width / 2.0 + tab_protrusion
    y_tab_bottom = -total_width / 2.0

    x_half = length / 2.0
    xt_half = tab_width / 2.0

    # clean rectangular main plate + centered rectangular tab on -Y side
    # sharp corners replace the ~1.33mm outer fillets (within 0.5mm)
    points = [
        (-x_half, y_top),
        (x_half, y_top),
        (x_half, y_main_bottom),
        (xt_half, y_main_bottom),
        (xt_half, y_tab_bottom),
        (-xt_half, y_tab_bottom),
        (-xt_half, y_main_bottom),
        (-x_half, y_main_bottom),
    ]

    part = pk.outline_from_points(points, thickness)

    # hole centered on the main rectangular plate (offset from bounding center)
    hole_center = (0.0, tab_protrusion / 2.0)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
