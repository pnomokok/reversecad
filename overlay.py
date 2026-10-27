"""Draw masks, SAM boxes and minAreaRect rectangles over a photo for visual checks."""
import cv2
import numpy as np


def draw_overlay(image_rgb, items):
    """items: list of (label, mask, sam_box, min_area_rect, color_bgr). Returns a BGR image."""
    canvas = cv2.cvtColor(np.asarray(image_rgb), cv2.COLOR_RGB2BGR)
    tinted = canvas.copy()
    for _, mask, _, _, color in items:
        tinted[mask] = color
    canvas = cv2.addWeighted(tinted, 0.45, canvas, 0.55, 0)

    thickness = max(2, canvas.shape[1] // 600)
    for label, _, box, rect, color in items:
        if box is not None:
            left, top, right, bottom = (int(round(v)) for v in box)
            # SAM box: thin axis-aligned rectangle; right/bottom are exclusive.
            cv2.rectangle(canvas, (left, top), (right - 1, bottom - 1), color, thickness)
            cv2.putText(canvas, label, (left, max(top - 10, 20)), cv2.FONT_HERSHEY_SIMPLEX,
                        thickness * 0.6, color, thickness)
        if rect is not None:
            # minAreaRect: white rotated rectangle used for the measurement.
            corners = cv2.boxPoints(rect).astype(np.int32)
            cv2.polylines(canvas, [corners], True, (255, 255, 255), thickness)
    return canvas
