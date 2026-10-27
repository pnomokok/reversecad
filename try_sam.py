"""SAM 3.1 scale test on the sample photo: card scale, key length, repeatability.

Sends the same photo RUNS times (one card request + one key request per run),
prints both mm/px ratios, an oblique-shot warning, the key length vs the ruler,
and the spread across runs. Saves overlays and raw SAM output to outputs/sam/
(git-ignored: the overlays show the card).

Run: .venv\\Scripts\\python.exe try_sam.py
"""
import statistics
from pathlib import Path

import cv2

from measure import MAX_RATIO_DIFFERENCE, card_scale, long_side_mm
from overlay import draw_overlay
from sam_client import load_photo, make_client, segment

PHOTO_PATH = Path("data") / "private" / "ornek_anahtar.jpg"
OUTPUT_DIR = Path("outputs") / "sam"
RUNS = 3
RULER_MM = (55.0, 56.0)  # key length measured with a ruler
CARD_PROMPT = "card"  # "credit card" returns nothing for the sample's transit card
PART_PROMPT = "key"


def best_detection(client, image, prompt, run):
    detections, raw_text = segment(client, image, prompt)
    (OUTPUT_DIR / f"run{run}_{prompt.replace(' ', '_')}_raw.txt").write_text(raw_text, encoding="utf-8")
    if not detections:
        raise RuntimeError(f"SAM found no '{prompt}' in run {run}")
    best = max(detections, key=lambda d: d.confidence or 0)
    print(f"  {prompt}: {len(detections)} detection(s), using confidence {best.confidence}")
    check_mask_inside_box(best)
    return best


def check_mask_inside_box(detection):
    """Verify the CLAUDE.md inference that SAM's mask covers the inside of its box."""
    ys, xs = detection.mask.nonzero()
    mask_box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    sam_box = tuple(round(v) for v in detection.box)
    box_size = (sam_box[2] - sam_box[0], sam_box[3] - sam_box[1])
    print(f"    raster {detection.mask_size[0]}x{detection.mask_size[1]}, SAM box size {box_size[0]}x{box_size[1]}")
    print(f"    mask extent {mask_box} vs SAM box {sam_box}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client()
    image = load_photo(PHOTO_PATH)
    print(f"photo {PHOTO_PATH} ({image.size[0]}x{image.size[1]} px after EXIF orientation)")

    ruler_mid = sum(RULER_MM) / 2
    lengths = []
    for run in range(1, RUNS + 1):
        print(f"\n=== run {run} ===")
        card = best_detection(client, image, CARD_PROMPT, run)
        key = best_detection(client, image, PART_PROMPT, run)

        scale = card_scale(card.mask)
        print(f"  mm/px from long edge  (85.60 mm): {scale.mm_per_pixel_long:.5f}")
        print(f"  mm/px from short edge (53.98 mm): {scale.mm_per_pixel_short:.5f}")
        print(f"  difference: {scale.relative_difference:.2%}")
        if scale.is_oblique:
            print(f"  WARNING: ratios differ by more than {MAX_RATIO_DIFFERENCE:.0%}; the shot is probably oblique")

        length, key_rect = long_side_mm(key.mask, scale.mm_per_pixel)
        lengths.append(length)
        in_range = RULER_MM[0] <= length <= RULER_MM[1]
        print(f"  key length: {length:.2f} mm (ruler {RULER_MM[0]}-{RULER_MM[1]} mm, "
              f"{(length - ruler_mid) / ruler_mid:+.2%} vs {ruler_mid} mm, "
              f"{'inside' if in_range else 'outside'} ruler range)")

        overlay = draw_overlay(image, [
            ("card", card.mask, card.box, scale.rect, (255, 140, 0)),
            ("key", key.mask, key.box, key_rect, (0, 0, 255)),
        ])
        cv2.imwrite(str(OUTPUT_DIR / f"run{run}_overlay.jpg"), overlay)

    print("\n=== repeatability ===")
    print(f"  key lengths: {', '.join(f'{v:.2f}' for v in lengths)} mm")
    print(f"  spread (max - min): {max(lengths) - min(lengths):.2f} mm")
    print(f"  standard deviation: {statistics.stdev(lengths):.3f} mm")
    print(f"overlays saved in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
