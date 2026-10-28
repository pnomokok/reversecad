import cadquery as cq
import partkit as pk
import math

def build_part(length=49.52, width=27.37, thickness=3.0, hole_diameter=10.05, tab_width=16.02, tab_protrusion=2.19, tab_radius=1.33):
    # main plate height is overall width minus tab protrusion
    main_width = width - tab_protrusion
    # bounding box centered at origin -> top at +width/2
    top_y = width / 2.0
    bottom_main_y = top_y - main_width  # = -width/2 + tab_protrusion
    bottom_tab_y = -width / 2.0
    hw = tab_width / 2.0

    # outline of main rectangle + centered tab on south edge (-Y)
    pts = [
        (-length/2, top_y),
        ( length/2, top_y),
        ( length/2, bottom_main_y),
        ( hw, bottom_main_y),
        ( hw, bottom_tab_y),
        (-hw, bottom_tab_y),
        (-hw, bottom_main_y),
        (-length/2, bottom_main_y),
    ]

    part = pk.outline_from_points(pts, thickness)

    # fillet the two re-entrant corners where tab meets main plate
    # vertical edges at (hw, bottom_main_y) and (-hw, bottom_main_y)
    if tab_radius > 0:
        try:
            part = part.edges(cq.NearestToPointSelector((hw, bottom_main_y, thickness/2))).fillet(tab_radius)
            part = part.edges(cq.NearestToPointSelector((-hw, bottom_main_y, thickness/2))).fillet(tab_radius)
        except Exception:
            pass

    # hole centered on main plate (which is tab_protrusion/2 north of bounding-box center)
    hole_center = (0.0, tab_protrusion/2.0)
    part = pk.cut_circle(part, hole_center, hole_diameter)

    return part
