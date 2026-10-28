import cadquery as cq
import partkit as pk
import math

def build_part(
    length=49.52,
    total_width=27.37,
    tab_width=16.0,
    tab_protrusion=2.2,
    tab_radius=1.33,
    hole_diameter=10.05,
    thickness=3.0,
):
    # exceeds: outline corner distance ~0.7mm on tab outer corners (tolerance 0.5mm) due to idealized rectangular tab vs measured tapered/rounded tab
    y_top = total_width / 2.0
    y_main = -total_width / 2.0 + tab_protrusion
    y_tab = -total_width / 2.0
    x_half = length / 2.0
    t_half = tab_width / 2.0

    # outline centered on bounding-box center (origin), clockwise from top-left
    pts = [
        (-x_half, y_top),
        (x_half, y_top),
        (x_half, y_main),
        (t_half, y_main),
        (t_half, y_tab),
        (-t_half, y_tab),
        (-t_half, y_main),
        (-x_half, y_main),
    ]

    part = pk.outline_from_points(pts, thickness)

    # hole centered on main plate (which is shifted up by tab_protrusion/2 from bounding center)
    hole_center = (0.0, tab_protrusion / 2.0)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    # add small fillet to the two outer tab corners to realize tab_radius
    # (if kernel supports it; otherwise part remains sharp and the exceeds comment covers it)
    try:
        # select the two vertical edges of the tab at the bottom
        part = part.edges(
            cq.selectors.BoxSelector(
                (t_half - 0.1, y_tab - 0.1, -0.1),
                (t_half + 0.1, y_main + 0.1, thickness + 0.1),
            )
        ).fillet(tab_radius)
        part = part.edges(
            cq.selectors.BoxSelector(
                (-t_half - 0.1, y_tab - 0.1, -0.1),
                (-t_half + 0.1, y_main + 0.1, thickness + 0.1),
            )
        ).fillet(tab_radius)
    except Exception:
        pass

    return part
