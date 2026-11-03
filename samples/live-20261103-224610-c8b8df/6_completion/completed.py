import cadquery as cq
import partkit as pk
import math

# The measured holes are not symmetric about the part centre (left centres at
# u=-41.76/-40.46, right at 37.56/38.58): a centred symmetric pattern exceeds
# the 0.5 mm hole-position limit by up to ~1.8 mm, so the four measured
# centres are kept as parameters with one shared hole diameter.
def build_part(
    length=106.6,
    width=96.53,
    thickness=3.0,
    chamfer=14.0,
    hole_diameter=6.0,
    hole_centers=(
        (-41.76, 38.52),
        (-40.46, -38.09),
        (37.56, 36.79),
        (38.58, -37.59),
    ),
    restored_corner_size=14.0,
):
    # Clean rectangular plate with a chamfer at the bottom-right (+X, -Y)
    # corner, built from length/width so the outline stays parametric.
    half_l = length / 2.0
    half_w = width / 2.0
    pts = [
        (-half_l, -half_w),
        (half_l - chamfer, -half_w),
        (half_l, -half_w + chamfer),
        (half_l, half_w),
        (-half_l, half_w),
    ]
    part = pk.outline_from_points(pts, thickness)

    # Restore the broken bottom-right corner: extend the bottom and right
    # edges to their intersection at (half_l, -half_w), adding only the
    # triangular material beyond the measured diagonal break.
    if restored_corner_size > 0:
        corner_pts = [
            (half_l - restored_corner_size, -half_w),
            (half_l, -half_w),
            (half_l, -half_w + restored_corner_size),
        ]
        corner = pk.outline_from_points(corner_pts, thickness)
        part = part.union(corner)

    # Four through-holes at the measured centres, one shared diameter.
    part = pk.hole_pattern(part, list(hole_centers), hole_diameter)

    return part
