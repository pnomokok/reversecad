import cadquery as cq
import partkit as pk
import math

def build_part(
    overall_length=49.52,
    overall_width=27.37,
    tab_width=15.0,
    tab_protrusion=2.15,
    tab_fillet_radius=1.33,
    hole_diameter=10.05,
    thickness=3.0,
):
    half_L = overall_length / 2.0
    top_y = overall_width / 2.0
    main_bottom_y = -top_y + tab_protrusion
    tab_bottom_y = -top_y
    tab_half_w = tab_width / 2.0
    r = tab_fillet_radius
    main_center_y = tab_protrusion / 2.0

    # 2D outline with filleted base corners of tab
    wp = cq.Workplane("XY")

    # start top-left
    wp = wp.moveTo(-half_L, top_y)
    wp = wp.lineTo(half_L, top_y)
    wp = wp.lineTo(half_L, main_bottom_y)
    wp = wp.lineTo(tab_half_w + r, main_bottom_y)
    # fillet arc right side: center at (tab_half_w + r, main_bottom_y - r)
    # from (tab_half_w + r, main_bottom_y) to (tab_half_w, main_bottom_y - r) 90deg clockwise
    wp = wp.threePointArc((tab_half_w + r * (1 - math.cos(math.pi/4)), main_bottom_y - r * math.sin(math.pi/4)), (tab_half_w, main_bottom_y - r))
    wp = wp.lineTo(tab_half_w, tab_bottom_y)
    wp = wp.lineTo(-tab_half_w, tab_bottom_y)
    wp = wp.lineTo(-tab_half_w, main_bottom_y - r)
    wp = wp.threePointArc((-tab_half_w - r * (1 - math.cos(math.pi/4)), main_bottom_y - r * math.sin(math.pi/4)), (-tab_half_w - r, main_bottom_y))
    wp = wp.lineTo(-half_L, main_bottom_y)
    wp = wp.close()

    part = wp.extrude(thickness)

    # central hole - centered in main rectangular portion (keeps symmetry when length/width change)
    hole_center = (0.0, main_center_y)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
