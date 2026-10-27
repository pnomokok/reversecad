"""Parametric rectangular plate with four through-holes near its corners.

All dimensions are in millimeters. The plate is centered on the origin,
lies on the XY plane, and its thickness runs along +Z.
"""
import cadquery as cq


def make_holed_plate(
    length=80.0,
    width=40.0,
    thickness=3.0,
    hole_diameter=6.0,
    hole_inset=8.0,
):
    """Build the plate.

    hole_inset is the distance from each outer edge to the hole centers.
    """
    return (
        cq.Workplane("XY")
        .box(length, width, thickness, centered=(True, True, False))
        .faces(">Z")
        .workplane()
        .rect(length - 2 * hole_inset, width - 2 * hole_inset, forConstruction=True)
        .vertices()
        .hole(hole_diameter)
    )
