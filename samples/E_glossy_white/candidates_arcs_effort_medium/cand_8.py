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
    # Base plate - rectangular outline
    part = pk.plate(length, width, thickness)

    # Two cutouts symmetric about origin, centered vertically
    # Rectangular hole on the left (-X side)
    part = pk.cut_rectangle(
        part,
        center=(-hole_spacing / 2.0, 0.0),
        length=rect_length,
        width=rect_width,
        angle=0.0,
    )

    # Slot hole on the right (+X side), length along X
    part = pk.cut_slot(
        part,
        center=(hole_spacing / 2.0, 0.0),
        length=slot_length,
        width=slot_width,
        angle=0.0,
    )

    return part
