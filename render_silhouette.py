"""Render the orthographic top-view silhouette of a CadQuery part as a binary mask.

The part is tessellated into triangles, every triangle is projected straight
down onto the XY plane (no perspective), and filled into an image. Vertical
faces project to zero-area slivers and are skipped. White (255) = part,
black (0) = background. Image rows grow downward, so world +Y points up in
the image, like a photo taken from above.

Run directly to save a sample render: .venv\\Scripts\\python.exe render_silhouette.py
"""
import math

import cv2
import numpy as np

# fillConvexPoly accepts fixed-point coordinates; 8 fractional bits = 1/256 px.
_SHIFT_BITS = 8
_SHIFT_SCALE = 1 << _SHIFT_BITS


def render_top_silhouette(workplane, mm_per_pixel, margin_mm=2.0, tolerance_mm=0.01):
    """Return a uint8 mask of the part seen from directly above.

    mm_per_pixel sets the image scale; margin_mm adds empty border on each side.
    """
    shape = workplane.val()
    vertices, triangles = shape.tessellate(tolerance_mm, 0.1)
    bbox = shape.BoundingBox()

    x_min = bbox.xmin - margin_mm
    y_max = bbox.ymax + margin_mm
    width_px = math.ceil((bbox.xlen + 2 * margin_mm) / mm_per_pixel)
    height_px = math.ceil((bbox.ylen + 2 * margin_mm) / mm_per_pixel)

    # World mm -> pixel coordinates; -0.5 puts pixel centers on the grid.
    points = np.array([(v.x, v.y) for v in vertices])
    px = (points[:, 0] - x_min) / mm_per_pixel - 0.5
    py = (y_max - points[:, 1]) / mm_per_pixel - 0.5
    pixel_points = np.stack([px, py], axis=1)

    mask = np.zeros((height_px, width_px), dtype=np.uint8)
    for triangle in triangles:
        corners = pixel_points[list(triangle)]
        a, b, c = corners
        doubled_area = abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))
        if doubled_area < 1e-6:
            continue  # vertical face, seen edge-on from above
        fixed = np.round(corners * _SHIFT_SCALE).astype(np.int32)
        cv2.fillConvexPoly(mask, fixed, 255, lineType=cv2.LINE_8, shift=_SHIFT_BITS)
    return mask


if __name__ == "__main__":
    from pathlib import Path

    from parts.holed_plate import make_holed_plate

    mm_per_pixel = 0.1
    mask = render_top_silhouette(make_holed_plate(), mm_per_pixel)
    output_path = Path("outputs") / "holed_plate_top.png"
    output_path.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(output_path), mask)

    area_mm2 = np.count_nonzero(mask) * mm_per_pixel**2
    print(f"saved {output_path} ({mask.shape[1]} x {mask.shape[0]} px)")
    print(f"silhouette area: {area_mm2:.1f} mm^2")
