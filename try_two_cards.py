"""Accuracy test with a part of exactly known size: two ID-1 cards in one photo.

SAM finds both cards with one "card" prompt. Each card is measured using the
other as the scale reference, once with the simple mean scale and once with
the homography, so every photo gives two measurements against a known
85.60 x 53.98 mm. Raw SAM output is cached in outputs/sam/ and reused, so
re-running costs nothing. Overlays and rectified views go to outputs/sam/.

Run: .venv\\Scripts\\python.exe try_two_cards.py
"""
from pathlib import Path

import cv2
import numpy as np

from homography import (
    card_corners,
    card_homography,
    edge_differences,
    largest_contour,
    rectify_image,
    to_mm,
)
from measure import CARD_LONG_MM, CARD_SHORT_MM, card_scale, min_area_rect, side_lengths_px
from overlay import draw_overlay
from sam_client import load_photo, make_client, parse_detections, segment

PHOTO_DIR = Path("data") / "private"
SAM_DIR = Path("outputs") / "sam"
# (label, file name, what is different about the shot)
PHOTOS = [
    ("cards_center", "cards_center.jpg", "both cards near the frame center"),
    ("cards_edges", "cards_edges.jpg", "cards at opposite edges of the frame"),
    ("cards_rotated", "cards_center_rotated.jpg", "cards rotated 90 degrees"),
]
PROMPT = "card"


def detect_cards(label, image, client_holder):
    """Two card detections, from the cached raw output if present, else from SAM."""
    raw_path = SAM_DIR / f"{label}_{PROMPT}_raw.txt"
    if raw_path.exists():
        detections = parse_detections(raw_path.read_text(encoding="utf-8"), image.size)
        print("  (using cached SAM output)")
    else:
        if not client_holder:
            client_holder.append(make_client())
        detections, raw_text = segment(client_holder[0], image, PROMPT)
        raw_path.write_text(raw_text, encoding="utf-8")
    if len(detections) < 2:
        raise RuntimeError(f"expected two cards in '{label}', SAM found {len(detections)}")
    if len(detections) > 2:
        print(f"  note: {len(detections)} detections, keeping the two most confident")
    cards = sorted(detections, key=lambda d: d.confidence or 0, reverse=True)[:2]
    return order_by_position(cards)


def order_by_position(cards):
    """Name the cards left/right or top/bottom, along the axis where they are farther apart."""
    centers = [np.argwhere(card.mask).mean(axis=0)[::-1] for card in cards]  # (x, y)
    dx, dy = np.abs(centers[1] - centers[0])
    axis, names = (0, ("left", "right")) if dx >= dy else (1, ("top", "bottom"))
    order = np.argsort([center[axis] for center in centers])
    return [(names[rank], cards[i]) for rank, i in enumerate(order)]


def measure_with_reference(reference_mask, part_mask):
    """Measure the part card both ways, using the reference card for scale."""
    simple_scale = card_scale(reference_mask).mm_per_pixel
    simple = side_lengths_px(min_area_rect(part_mask))
    simple = (simple[0] * simple_scale, simple[1] * simple_scale)

    reference_contour = largest_contour(reference_mask)
    corners = card_corners(reference_contour)
    homography, _ = card_homography(corners)
    part_mm = to_mm(largest_contour(part_mask), homography)
    corrected = tuple(sorted(cv2.minAreaRect(part_mm.astype(np.float32))[1], reverse=True))

    reference_mm = to_mm(reference_contour, homography)
    distance = np.linalg.norm(part_mm.mean(axis=0) - reference_mm.mean(axis=0)) / CARD_LONG_MM
    return {
        "simple": simple,
        "homography": corrected,
        "edges_before": edge_differences(corners),
        "distance": distance,
        "homography_matrix": homography,
        "reference_mm": reference_mm,
        "part_mm": part_mm,
    }


def save_rectified(name, image, result):
    points = np.vstack([result["reference_mm"], result["part_mm"]])
    region = (*(points.min(axis=0) - 10), *(points.max(axis=0) + 10))
    view, to_pixels = rectify_image(image, result["homography_matrix"], region)
    view = cv2.cvtColor(view, cv2.COLOR_RGB2BGR)
    for outline, color in [(result["reference_mm"], (255, 140, 0)), (result["part_mm"], (0, 0, 255))]:
        cv2.polylines(view, [to_mm(outline, to_pixels).round().astype(np.int32)], True, color, 2)
    cv2.imwrite(str(SAM_DIR / f"{name}_rectified.jpg"), view)


def error(measured, true):
    return (measured - true) / true


def main():
    SAM_DIR.mkdir(parents=True, exist_ok=True)
    client_holder = []
    rows = []
    for label, file_name, note in PHOTOS:
        print(f"\n=== {label}: {file_name} ({note}) ===")
        image = load_photo(PHOTO_DIR / file_name)
        (name_a, card_a), (name_b, card_b) = detect_cards(label, image, client_holder)
        cv2.imwrite(str(SAM_DIR / f"{label}_overlay.jpg"), draw_overlay(image, [
            (name_a, card_a.mask, card_a.box, None, (255, 140, 0)),
            (name_b, card_b.mask, card_b.box, None, (0, 0, 255)),
        ]))
        for (ref_name, reference), (part_name, part) in [((name_a, card_a), (name_b, card_b)),
                                                         ((name_b, card_b), (name_a, card_a))]:
            result = measure_with_reference(reference.mask, part.mask)
            save_rectified(f"{label}_{part_name}_by_{ref_name}", image, result)
            rows.append((label, f"{part_name} by {ref_name}", result))

    print("\nmeasured card vs true 85.60 x 53.98 mm (reference = the other card):")
    print(f"  {'photo':13s} {'card':17s} {'ref edges L-R/T-B':>18s} {'dist':>5s}"
          f"   {'simple long':>11s} {'err':>7s} {'short':>6s} {'err':>7s}"
          f"   {'homog long':>10s} {'err':>7s} {'short':>6s} {'err':>7s}")
    for label, name, r in rows:
        (s_long, s_short), (h_long, h_short) = r["simple"], r["homography"]
        lr, tb = r["edges_before"]
        print(f"  {label:13s} {name:17s} {lr:+8.2%}/{tb:+8.2%} {r['distance']:4.2f}x"
              f"   {s_long:11.2f} {error(s_long, CARD_LONG_MM):+7.2%} {s_short:6.2f} {error(s_short, CARD_SHORT_MM):+7.2%}"
              f"   {h_long:10.2f} {error(h_long, CARD_LONG_MM):+7.2%} {h_short:6.2f} {error(h_short, CARD_SHORT_MM):+7.2%}")

    for method in ("simple", "homography"):
        errors = [abs(error(r[method][0], CARD_LONG_MM)) for _, _, r in rows]
        errors += [abs(error(r[method][1], CARD_SHORT_MM)) for _, _, r in rows]
        print(f"  mean absolute error, {method}: {np.mean(errors):.2%} (max {np.max(errors):.2%})")
    print(f"overlays and rectified views saved in {SAM_DIR}")


if __name__ == "__main__":
    main()
