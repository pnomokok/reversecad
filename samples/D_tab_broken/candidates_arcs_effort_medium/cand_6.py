import cadquery as cq
import partkit as pk
import math

def build_part(length=49.52, width=27.37, thickness=3.0, tab_width=16.0, tab_length=2.2, tab_corner_radius=1.33, hole_diameter=10.05):
    # exceeds: tab corner position by ~0.7mm (tapered/irregular measured tab cleaned to rectangular tab) and tab corner radius by ~1.3mm (sharp tab vs measured fillet)
    # overall bounding is length x width, tab protrudes from the long edge
    main_width = width - tab_length
    main_center_y = tab_length / 2.0  # so overall top = width/2, bottom of main = -width/2 + tab_length

    # main rectangular body
    part = pk.plate(length, main_width, thickness)
    # move main body up so its top aligns with overall top
    part = part.translate((0, main_center_y, 0))

    # centered tab on the -Y edge (measured at -Y, image shows it on top - orientation equivalent)
    base_center = (0.0, -width / 2.0 + tab_length)
    # angle 270 = -Y outward
    part = pk.tab(part, base_center, tab_length, tab_width, 270)

    # central hole
    part = pk.cut_circle(part, (0.0, 1.06), hole_diameter)

    return part
