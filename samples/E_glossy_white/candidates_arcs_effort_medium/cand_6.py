import cadquery as cq
import partkit as pk
import math

def build_part(
    length=69.35,
    width=40.26,
    thickness=3.0,
    rect_length=16.0,
    rect_width=8.23,
    slot_length=19.84,
    slot_width=6.22,
    hole_spacing=29.65,
):
    # Outline is a simple rectangle centered at origin
    part = pk.plate(length, width, thickness)

    # Two through-holes placed symmetrically about the origin along X
    # hole_spacing is distance between centers: 14.75 - (-14.9) = 29.65
    # Y offset is nominally 0 (measured -0.08/-0.09 is noise)
    rect_center = (-hole_spacing / 2.0, 0.0)
    slot_center = (hole_spacing / 2.0, 0.0)

    part = pk.cut_rectangle(part, rect_center, rect_length, rect_width, angle=0.0)
    part = pk.cut_slot(part, slot_center, slot_length, slot_width, angle=0.0)

    return part
