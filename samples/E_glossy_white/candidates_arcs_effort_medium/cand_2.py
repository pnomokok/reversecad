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
    hole_y=0.0,
):
    # Base plate - rectangular outline
    part = pk.plate(length, width, thickness)

    # Two holes symmetric about origin along length
    # left: rectangle, right: slot (semicircular ends)
    rect_center = (-hole_spacing / 2.0, hole_y)
    slot_center = (hole_spacing / 2.0, hole_y)

    part = pk.cut_rectangle(part, rect_center, rect_length, rect_width, angle=0.0)
    part = pk.cut_slot(part, slot_center, slot_length, slot_width, angle=0.0)

    return part
