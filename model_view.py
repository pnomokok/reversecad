"""The measurement table as the language model sees it, and as candidates are checked against.

The measurement table itself is not changed. For the model, the outline is the
simplified one (least-squares edges, torn edges flattened; see
part_measurements.least_squares_outline) and every coordinate is re-centered on
that outline's bounding box, so a candidate centered the usual way lines up with
it. Holes keep all their measured fields here; the prompt shows only the fields
each hole shape needs.
"""
import copy

import numpy as np


def model_view(table):
    polygon = np.array(table["outline"]["simplified_polygon_mm"], dtype=float)
    low, high = polygon.min(axis=0), polygon.max(axis=0)
    center = (low + high) / 2

    def shift(point):
        return [round(float(point[0] - center[0]), 2), round(float(point[1] - center[1]), 2)]

    holes = []
    for hole in table["holes"]:
        hole = copy.deepcopy(hole)
        hole["center_from_part_center_mm"] = shift(hole["center_from_part_center_mm"])
        if "polygon_mm" in hole:
            hole["polygon_mm"] = [shift(p) for p in hole["polygon_mm"]]
        holes.append(hole)
    return {
        "outline": {
            "length_mm": round(float(high[0] - low[0]), 2),
            "width_mm": round(float(high[1] - low[1]), 2),
            "vertex_count": len(polygon),
            "polygon_mm": [shift(p) for p in polygon],
        },
        "hole_count": len(holes),
        "holes": holes,
    }
