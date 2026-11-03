import cadquery as cq
import partkit as pk
import math

def build_part(
    part_length=69.35,
    part_width=40.26,
    thickness=3.0,
    rect_length=16.0,
    rect_width=8.23,
    slot_length=19.84,
    slot_width=6.22,
    hole_spacing=29.65,
):
    # Base plate centered at origin, bottom at Z=0
    part = pk.plate(part_length, part_width, thickness)

    # Two cutouts symmetric about origin along X; Y centered
    # Derived from measured centers -14.9 and +14.75 -> spacing ~29.65
    rect_center = (-hole_spacing / 2.0, 0.0)
    slot_center = (hole_spacing / 2.0, 0.0)

    part = pk.cut_rectangle(part, center=rect_center, length=rect_length, width=rect_width, angle=0.0)
    part = pk.cut_slot(part, center=slot_center, length=slot_length, width=slot_width, angle=0.0)

    return part
