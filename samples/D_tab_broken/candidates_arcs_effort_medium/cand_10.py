import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.52,
    width=27.37,
    thickness=3.0,
    tab_width=17.0,
    tab_protrusion=2.2,
    tab_corner_radius=1.33,
    hole_diameter=10.05
):
    # main plate bottom and top in bounding-box coordinates (origin at bounding center)
    main_bottom = -width / 2 + tab_protrusion
    main_top = width / 2
    half_len = length / 2
    half_tab = tab_width / 2
    r = tab_corner_radius
    bottom = -width / 2

    # outline clockwise from top-left, tab on the -Y side with outer fillets
    pts = [
        (-half_len, main_top),
        (half_len, main_top),
        (half_len, main_bottom),
        (half_tab, main_bottom),
        (half_tab, bottom + r),
        (half_tab - r, bottom),
        (-half_tab + r, bottom),
        (-half_tab, bottom + r),
        (-half_tab, main_bottom),
        (-half_len, main_bottom),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centered in the main rectangular body (center of bounding box shifted by tab_protrusion/2)
    # keeps symmetry when length/width change
    hole_center = (0.0, tab_protrusion / 2)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
