"""SAM 3.1 scale test across several photos of the same key and card.

For each photo: one card request + one key request, both mm/px ratios, an
oblique-shot warning, and the key length vs the ruler. Ends with the spread of
key lengths across photos. Each photo gets its own scale from the card, so
camera distance should not change the result. Saves overlays and raw SAM
output to outputs/sam/ (git-ignored: the overlays show the card).

Run: .venv\\Scripts\\python.exe try_sam.py
"""
import statistics
from pathlib import Path

import cv2

from homography import MAX_EDGE_DIFFERENCE, card_corners, edge_differences, is_tilted, largest_contour
from measure import card_scale, long_side_mm, side_lengths_px
from overlay import draw_overlay
from sam_client import load_photo, make_client, segment

PHOTO_DIR = Path("data") / "private"
# (label, file name, what is different about the shot)
PHOTOS = [
    ("original", "ornek_anahtar.jpg", "reference shot"),
    ("closer", "key_repeat_1.jpg.jpeg", "camera closer"),
    ("swapped", "key_replace.png.jpeg", "positions swapped, key rotated, camera farther"),
    ("blurred", "key_repeat_blur.jpg.jpeg", "out of focus"),
]
OUTPUT_DIR = Path("outputs") / "sam"
RULER_MM = (56.5, 57.5)  # key length, physical ruler reading 57 mm +/- 0.5 mm
CARD_PROMPT = "card"  # "credit card" returns nothing for the sample's transit card
PART_PROMPT = "key"


def best_detection(client, image, prompt, label):
    detections, raw_text = segment(client, image, prompt)
    (OUTPUT_DIR / f"{label}_{prompt.replace(' ', '_')}_raw.txt").write_text(raw_text, encoding="utf-8")
    if not detections:
        raise RuntimeError(f"SAM found no '{prompt}' in photo '{label}'")
    best = max(detections, key=lambda d: d.confidence or 0)
    print(f"  {prompt}: {len(detections)} detection(s), confidence {best.confidence:.3f}")
    box_size = (round(best.box[2] - best.box[0]), round(best.box[3] - best.box[1]))
    if best.mask_size != box_size:
        print(f"    mask raster {best.mask_size[0]}x{best.mask_size[1]} scaled up to box {box_size[0]}x{box_size[1]}")
    return best


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client()
    ruler_mid = sum(RULER_MM) / 2
    rows = []

    for label, file_name, note in PHOTOS:
        image = load_photo(PHOTO_DIR / file_name)
        print(f"\n=== {label}: {file_name} ({note}) ===")
        card = best_detection(client, image, CARD_PROMPT, label)
        key = best_detection(client, image, PART_PROMPT, label)

        scale = card_scale(card.mask)
        card_long_px, _ = side_lengths_px(scale.rect)
        print(f"  card long side: {card_long_px:.0f} px")
        print(f"  mm/px long edge {scale.mm_per_pixel_long:.5f}, short edge {scale.mm_per_pixel_short:.5f}")
        differences = edge_differences(card_corners(largest_contour(card.mask)))
        print(f"  card edges: left vs right {differences[0]:+.2%}, top vs bottom {differences[1]:+.2%}")
        if is_tilted(differences):
            print(f"  WARNING: opposite card edges differ by more than {MAX_EDGE_DIFFERENCE:.0%}; the camera is tilted")

        length, key_rect = long_side_mm(key.mask, scale.mm_per_pixel)
        error = (length - ruler_mid) / ruler_mid
        in_range = RULER_MM[0] <= length <= RULER_MM[1]
        print(f"  key length: {length:.2f} mm ({error:+.2%} vs {ruler_mid} mm, "
              f"{'inside' if in_range else 'outside'} ruler range {RULER_MM[0]}-{RULER_MM[1]})")
        rows.append((label, card_long_px, max(differences, key=abs), length, error))

        overlay = draw_overlay(image, [
            ("card", card.mask, card.box, scale.rect, (255, 140, 0)),
            ("key", key.mask, key.box, key_rect, (0, 0, 255)),
        ])
        cv2.imwrite(str(OUTPUT_DIR / f"{label}_overlay.jpg"), overlay)

    print("\n=== summary ===")
    print(f"  {'photo':10s} {'card px':>8s} {'edge diff':>10s} {'key mm':>8s} {'error':>8s}")
    for label, card_px, edge_diff, length, error in rows:
        print(f"  {label:10s} {card_px:8.0f} {edge_diff:+10.2%} {length:8.2f} {error:+8.2%}")
    lengths = [row[3] for row in rows]
    print(f"  spread (max - min): {max(lengths) - min(lengths):.2f} mm, "
          f"standard deviation: {statistics.stdev(lengths):.3f} mm")
    print(f"overlays saved in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
