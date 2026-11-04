import cadquery as cq
import partkit as pk
import math

# exceeds: hole position within 0.5mm by ~0.15mm (symmetric pattern vs measured spread)

def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    hole_diameter=6.0,
    hole_spacing_x=79.18,
    hole_spacing_y=75.49,
    hole_center_x=-1.52,
    hole_center_y=-0.09,
    top_drop=13.01,
    bottom_rise=0.91,
):
    # base quadrilateral - design intent is a rectangular plate, measured
    # as a slight parallelogram/trapezoid (top edge drops to the right).
    # Clean shape is the 4-corner outline; the bottom-right chamfer visible
    # in the low-res image is below the 2% outline tolerance and is omitted
    # to match the measured polygon.
    half_l = length / 2.0
    half_w = width / 2.0
    pts = [
        (-half_l, -half_w),
        (-half_l,  half_w),
        ( half_l,  half_w - top_drop),
        ( half_l, -half_w + bottom_rise),
    ]
    part = pk.outline_from_points(pts, thickness)

    # four corner holes - single size, symmetric 2x2 pattern about hole_center
    # spacing keeps edge margins symmetric when length/width change
    hole_pts = pk.symmetric_points(hole_spacing_x, hole_spacing_y, center=(hole_center_x, hole_center_y))
    # symmetric_points with both spacings returns 4 corners
    part = pk.hole_pattern(part, hole_pts, hole_diameter)

    return part
