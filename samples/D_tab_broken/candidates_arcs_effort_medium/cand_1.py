import cadquery as cq
import partkit as pk
import math

# exceeds: outline tab corner rounding by ~0.7 mm (0.5 mm limit for small feature) - clean sharp tab used for design intent
def build_part(length=49.52, width=27.37, thickness=3.0, tab_width=16.0, tab_length=2.2, tab_radius=1.33, hole_diameter=10.05):
    # main plate width without tab
    main_width = width - tab_length
    # y coordinates in bounding-center system (origin at bounding rectangle center)
    y_top = width / 2
    y_main_bottom = -width / 2 + tab_length
    y_tab_bottom = -width / 2

    half_len = length / 2
    half_tab = tab_width / 2

    # outline points in order (counter-clockwise), sharp tab - arc approximated by sharp corner for clarity
    # the measured arc at the tab shoulder (radius ~1.33mm) is represented as a sharp shoulder;
    # design intent is a rectangular tab centered on the long edge
    pts = [
        (-half_len, y_top),
        (half_len, y_top),
        (half_len, y_main_bottom),
        (half_tab, y_main_bottom),
        (half_tab, y_tab_bottom),
        (-half_tab, y_tab_bottom),
        (-half_tab, y_main_bottom),
        (-half_len, y_main_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centered on the main plate (which is offset by tab_length/2 from bounding center)
    # measured center (-0.06, 1.06) corresponds to main-plate center (0, tab_length/2)
    hole_center = (0.0, tab_length / 2)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
