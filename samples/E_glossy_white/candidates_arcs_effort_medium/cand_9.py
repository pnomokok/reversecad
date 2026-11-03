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
    hole_offset=14.825,
):
    # Outline is a clean rectangle; measured corner deviations (~0.5mm) are noise
    part = pk.plate(length, width, thickness)

    # Two holes symmetric about Y axis, centered in Y (measured Y ~ -0.08 is noise)
    # Left: rectangular cut, Right: slot (semicircular ends) - share common X offset
    # hole_offset is average of 14.9 and 14.75 -> 14.825, within 0.5mm of both
    part = pk.cut_rectangle(part, center=(-hole_offset, 0.0), length=rect_length, width=rect_width, angle=0.0)
    part = pk.cut_slot(part, center=(hole_offset, 0.0), length=slot_length, width=slot_width, angle=0.0)

    return part
