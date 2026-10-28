import cadquery as cq
import partkit as pk


def build_part(
    thickness=3.0,
    length=79.31,
    width=40.26,
    edge_margin=8.0,
    hole_diameter=6.04,
):
    part = pk.plate(length, width, thickness)
    hole_spacing_x = length - 2 * edge_margin
    hole_spacing_y = width - 2 * edge_margin
    points = pk.symmetric_points(hole_spacing_x, hole_spacing_y)
    part = pk.hole_pattern(part, points, hole_diameter)
    return part
