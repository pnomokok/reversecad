import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.35,
    width=40.26,
    thickness=3.0,
    hole_spacing=29.65,
    rect_length=16.0,
    rect_width=8.23,
    slot_length=19.84,
    slot_width=6.22,
):
    # Base plate - rectangular outline centered at origin
    part = pk.plate(length, width, thickness)

    # Hole centers placed symmetrically about origin using shared spacing
    # Left: rectangular cutout, Right: slot cutout
    rect_center = (-hole_spacing / 2.0, 0.0)
    slot_center = (hole_spacing / 2.0, 0.0)

    part = pk.cut_rectangle(part, rect_center, rect_length, rect_width, angle=0.0)
    part = pk.cut_slot(part, slot_center, slot_length, slot_width, angle=0.0)

    return part
