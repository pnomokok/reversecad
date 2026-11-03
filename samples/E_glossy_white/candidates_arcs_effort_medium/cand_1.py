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

    # Holes are symmetric about origin along X, centered on Y=0
    # hole_spacing = distance between rectangle and slot centers
    rect_center = (-hole_spacing / 2.0, 0.0)
    slot_center = (hole_spacing / 2.0, 0.0)

    part = pk.cut_rectangle(part, rect_center, rect_length, rect_width, angle=0.0)
    part = pk.cut_slot(part, slot_center, slot_length, slot_width, angle=0.0)

    return part
