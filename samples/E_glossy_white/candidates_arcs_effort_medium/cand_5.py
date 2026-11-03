import cadquery as cq
import partkit as pk
import math

def build_part(
    plate_length=69.35,
    plate_width=40.26,
    thickness=3.0,
    rect_length=16.0,
    rect_width=8.23,
    slot_length=19.84,
    slot_width=6.22,
    hole_spacing=29.65,
):
    # Base plate - clean rectangle for slightly noisy measured outline
    part = pk.plate(plate_length, plate_width, thickness)

    # Two cutouts centered vertically, placed symmetrically about origin
    # hole_spacing is distance between hole centers (-hole_spacing/2 and +hole_spacing/2)
    # keeps symmetry if plate_length changes
    left_center = (-hole_spacing / 2.0, 0.0)
    right_center = (hole_spacing / 2.0, 0.0)

    part = pk.cut_rectangle(part, center=left_center, length=rect_length, width=rect_width, angle=0.0)
    part = pk.cut_slot(part, center=right_center, length=slot_length, width=slot_width, angle=0.0)

    return part
