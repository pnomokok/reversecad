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
    # Base plate - rectangle from outline length/width
    part = pk.plate(length, width, thickness)

    # Symmetric hole layout: two holes mirrored about origin along X
    # hole_spacing is distance between hole centers (14.9 + 14.75 from table)
    rect_center = (-hole_spacing / 2.0, 0.0)
    slot_center = (hole_spacing / 2.0, 0.0)

    # Rectangular through-hole on the left
    part = pk.cut_rectangle(part, center=rect_center, length=rect_length, width=rect_width, angle=0.0)

    # Slot through-hole on the right (semicircular ends)
    part = pk.cut_slot(part, center=slot_center, length=slot_length, width=slot_width, angle=0.0)

    return part
