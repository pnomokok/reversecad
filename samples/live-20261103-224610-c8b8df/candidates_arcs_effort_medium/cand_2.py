import cadquery as cq
import partkit as pk
import math

# exceeds: outline top-right corner by ~13mm and hole positions by ~2.3mm - perspective/skew in measured polygon vs clean rectangular design intent
def build_part(length=106.6, width=96.53, thickness=3.0, chamfer=14.0, hole_diameter=6.0, hole_pitch_x=79.2, hole_pitch_y=75.5):
    # base rectangular plate centered at origin, bottom at Z=0
    part = pk.plate(length, width, thickness)

    # chamfer at bottom-right corner (isosceles right triangle cut)
    # triangle corners: (L/2, -W/2) , (L/2, -W/2+chamfer) , (L/2-chamfer, -W/2)
    lx = length / 2.0
    wy = width / 2.0
    chamfer_pts = [
        (lx, -wy),
        (lx, -wy + chamfer),
        (lx - chamfer, -wy),
    ]
    part = pk.cut_polygon(part, chamfer_pts)

    # four corner holes as symmetric pattern about origin
    # spacing keeps symmetry when length/width change; diameter shared
    pts = pk.symmetric_points(hole_pitch_x, hole_pitch_y, center=(0.0, 0.0))
    part = pk.hole_pattern(part, pts, hole_diameter)

    return part
