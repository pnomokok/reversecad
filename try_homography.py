"""Compare key length before and after homography on the four sample photos.

Works offline from the raw SAM output saved by try_sam.py (outputs/sam/),
so it makes no API calls. For each photo it prints opposite-edge differences
of the card before and after correction, the corrected card size, the key's
distance from the card (in card lengths) and the key length both ways.
Saves a top-down rectified view per photo to outputs/sam/.

Run: .venv\\Scripts\\python.exe try_homography.py
"""
from pathlib import Path

import cv2
import numpy as np

from homography import (
    card_corners,
    card_homography,
    edge_differences,
    is_tilted,
    largest_contour,
    long_side_mm,
    rectify_image,
    to_mm,
)
from measure import CARD_LONG_MM, card_scale
from measure import long_side_mm as naive_long_side_mm
from sam_client import load_photo, parse_detections
from try_sam import CARD_PROMPT, PART_PROMPT, PHOTO_DIR, PHOTOS, RULER_MM

SAM_DIR = Path("outputs") / "sam"


def load_mask(label, prompt, image_size):
    raw_text = (SAM_DIR / f"{label}_{prompt.replace(' ', '_')}_raw.txt").read_text(encoding="utf-8")
    detections = parse_detections(raw_text, image_size)
    return max(detections, key=lambda d: d.confidence or 0).mask


def save_rectified(label, image, homography, card_mm, key_mm):
    points = np.vstack([card_mm, key_mm])
    region = (*(points.min(axis=0) - 10), *(points.max(axis=0) + 10))
    view, to_pixels = rectify_image(image, homography, region)
    view = cv2.cvtColor(view, cv2.COLOR_RGB2BGR)
    for outline, color in [(card_mm, (255, 140, 0)), (key_mm, (0, 0, 255))]:
        pixels = to_mm(outline, to_pixels).round().astype(np.int32)  # mm -> view pixels
        cv2.polylines(view, [pixels], True, color, 2)
    cv2.imwrite(str(SAM_DIR / f"{label}_rectified.jpg"), view)


def percent_error(length):
    middle = sum(RULER_MM) / 2
    return (length - middle) / middle


def main():
    rows = []
    for label, file_name, note in PHOTOS:
        image = load_photo(PHOTO_DIR / file_name)
        card_mask = load_mask(label, CARD_PROMPT, image.size)
        key_mask = load_mask(label, PART_PROMPT, image.size)

        # Before: simple mean scale, no perspective correction.
        naive_length, _ = naive_long_side_mm(key_mask, card_scale(card_mask).mm_per_pixel)
        card_contour = largest_contour(card_mask)
        corners = card_corners(card_contour)
        before = edge_differences(corners)

        # After: map outlines to mm on the table plane, refit the card's corners there.
        homography, (card_width, card_height) = card_homography(corners)
        card_mm = to_mm(card_contour, homography)
        key_mm = to_mm(largest_contour(key_mask), homography)
        after = edge_differences(card_corners(card_mm))
        card_size = sorted(cv2.minAreaRect(card_mm.astype(np.float32))[1], reverse=True)
        corrected_length, _ = long_side_mm(key_mm)

        key_center = key_mm.mean(axis=0)
        card_center = np.array([card_width / 2, card_height / 2])
        distance = np.linalg.norm(key_center - card_center) / CARD_LONG_MM

        rows.append((label, before, after, card_size, distance, naive_length, corrected_length))
        save_rectified(label, image, homography, card_mm, key_mm)
        print(f"{label:9s} ({note}): tilt warning before correction: {'YES' if is_tilted(before) else 'no'}")

    print("\nopposite-edge differences of the card (left vs right, top vs bottom):")
    print(f"  {'photo':9s} {'L-R before':>10s} {'T-B before':>10s} {'L-R after':>10s} {'T-B after':>10s}"
          f"   card after (mm)")
    for label, before, after, card_size, *_ in rows:
        print(f"  {label:9s} {before[0]:+10.2%} {before[1]:+10.2%} {after[0]:+10.2%} {after[1]:+10.2%}"
              f"   {card_size[0]:.2f} x {card_size[1]:.2f}")

    print(f"\nkey length (ruler {RULER_MM[0]}-{RULER_MM[1]} mm, errors vs {sum(RULER_MM) / 2} mm):")
    print(f"  {'photo':9s} {'distance':>9s} {'before':>8s} {'error':>8s} {'after':>8s} {'error':>8s}")
    for label, _, _, _, distance, naive_length, corrected_length in rows:
        print(f"  {label:9s} {distance:8.2f}x {naive_length:8.2f} {percent_error(naive_length):+8.2%}"
              f" {corrected_length:8.2f} {percent_error(corrected_length):+8.2%}")
    print("  distance = key center to card center, in card lengths (85.60 mm)")
    print(f"rectified views saved in {SAM_DIR}")


if __name__ == "__main__":
    main()
