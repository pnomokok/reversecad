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
    # Base plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # Holes are symmetric about origin along length axis
    # hole_spacing is center-to-center distance between rectangle and slot
    # derived from measured centers: 14.9 + 14.75 = 29.65
    half = hole_spacing / 2.0
    left_center = (-half, 0.0)
    right_center = (half, 0.0)

    # Rectangular through-hole on the left (-u side)
    part = pk.cut_rectangle(part, left_center, rect_length, rect_width, angle=0.0)

    # Slot (semicircular ends) on the right (+u side)
    part = pk.cut_slot(part, right_center, slot_length, slot_width, angle=0.0)

    return part
