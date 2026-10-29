"""Run the pipeline on real photos in data/private and compare with hand measurements.

Each part has one entry in PARTS: its photos (each with a card for scale and a click,
a pixel on the part chosen by looking at the photo) and the values measured by hand
(ruler or caliper): outline length x width and each hole, either a diameter (round)
or (length, width). Outputs go to outputs/real/<part>/ (git-ignored; they show the card),
or outputs/real/<part>_<n>/ when a part has several photos.

Besides the pipeline's outline (maximum extent), the report shows the median length and
width across the part and the card's length in pixels. Report only: the pipeline and its
measurements are unchanged.

Run all:   .venv\\Scripts\\python.exe run_real_photos.py
Run some:  .venv\\Scripts\\python.exe run_real_photos.py carton
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from e2e_pipeline import pixel_to_mm_scales, run_photo
from homography import largest_contour, to_mm
from resolution import MIN_CARD_PX, card_long_edge_px

PHOTO_DIR = Path("data") / "private"
OUT = Path("outputs") / "real"

MEDIAN_RASTER_MM = 0.1  # raster step for the median extents
MEDIAN_SPAN = 0.8  # medians over the middle 80% of the part, away from rounded ends
MIN_FILL_FOR_MEDIAN = 0.85  # below this outline/rectangle area ratio (a key: 0.53) the medians say little

# To add a part: copy an entry. "click" is (x, y) in pixels of the photo as it appears on screen.
# "measured" holds the hand values; "tool" says how they were taken. Holes: a number (diameter)
# or (length, width), largest first.
PARTS = {
    # Earlier rounds: candidates_intent/ (no code, stuck on the torn edge), candidates_clean/ (clean shapes
    # allowed), candidates_kit/ (partkit; no code, contradictory limits). Kept as a hard input, no special tuning.
    "carton": {"photos": [{"file": "carton_with_card.jpeg", "click": (550, 980)}],
               "measured": {"tool": "ruler", "length": 188, "width": 91, "holes": [(20, 8), (13, 7)]},
               "candidates": 10, "candidates_folder": "candidates_arcs_effort_medium"},
    "key": {"photos": [{"file": "key_with_card.jpeg", "click": (480, 1103)}],
            "measured": {"tool": "ruler", "length": 57, "width": 22.5, "holes": [(12, 6)]},
            "candidates": 0},  # outline out of scope
    # Stress test: the pockets are blind cavities under clear plastic domes, not through-holes.
    # The user asked that this photo never leaves data/private (only SAM may see it): outputs stay there
    # and no prompt suggestions are requested.
    "blister": {"photos": [{"file": "drug_with_card.jpeg", "click": (720, 1080)}],
                "measured": {"tool": "ruler", "length": 70.5, "width": 52, "holes": [23] * 4},
                "candidates": 0, "out": PHOTO_DIR / "blister_run", "suggest": False},
}


def hole_size(hole):
    if hole["shape"] == "circle":
        return hole["diameter_mm"], hole["diameter_mm"]
    return hole["length_mm"], hole["width_mm"]  # for a polygon: its bounding rectangle


def median_extents(part_mask, pixel_to_mm):
    """Median length and width across the part, in mm, along its minAreaRect axes (holes ignored)."""
    outline = to_mm(largest_contour(part_mask).reshape(-1, 2), pixel_to_mm)
    (cx, cy), (w, h), angle = cv2.minAreaRect(outline.astype(np.float32))
    turn = np.radians(angle if w >= h else angle + 90)
    rotation = np.array([[np.cos(turn), np.sin(turn)], [-np.sin(turn), np.cos(turn)]])
    local = (outline - (cx, cy)) @ rotation.T / MEDIAN_RASTER_MM  # length along x, width along y
    local -= local.min(axis=0) - 1
    size = np.ceil(local.max(axis=0)).astype(int) + 2
    raster = np.zeros((size[1], size[0]), np.uint8)
    cv2.fillPoly(raster, [np.round(local).astype(np.int32)], 1)

    def middle_median(counts):
        filled = np.nonzero(counts)[0]
        first, last = filled[0], filled[-1]
        cut = int((1 - MEDIAN_SPAN) / 2 * (last - first))
        spans = counts[first + cut:last - cut + 1]
        return float(np.median(spans[spans > 0])) * MEDIAN_RASTER_MM

    ys, xs = np.nonzero(raster)
    rows = np.zeros(size[1]); cols = np.zeros(size[0])
    for y in np.unique(ys):
        row = xs[ys == y]
        rows[y] = row.max() - row.min() + 1
    for x in np.unique(xs):
        col = ys[xs == x]
        cols[x] = col.max() - col.min() + 1
    return middle_median(rows), middle_median(cols)


def extra_measurements(out, hole_method):
    """Card length in pixels and the part's median extents, from the masks the pipeline saved."""
    card_mask = cv2.imread(str(out / "3_mask_card.png"), cv2.IMREAD_GRAYSCALE) > 0
    part_mask = cv2.imread(str(out / f"3_mask_{hole_method}.png"), cv2.IMREAD_GRAYSCALE) > 0
    card_px = card_long_edge_px(card_mask)
    scales, scale_used, _ = pixel_to_mm_scales(card_mask)
    return card_px, median_extents(part_mask, scales[scale_used])


def percent(value, reference):
    return f"{(value - reference) / reference:+.1%}"


def compare(name, measured, table, card_px, medians):
    length, width = table["outline"]["length_mm"], table["outline"]["width_mm"]
    ref_length, ref_width = measured["length"], measured["width"]
    median_length, median_width = medians
    print(f"\n[{measured['tool']}] {name}: card {card_px:.0f} px long"
          f"{f'  WARNING: under {MIN_CARD_PX} px, small holes and edges lose precision' if card_px < MIN_CARD_PX else ''}")
    print(f"        outline max    {length:.1f} x {width:.1f} mm vs {ref_length} x {ref_width} "
          f"({percent(length, ref_length)} / {percent(width, ref_width)})")
    print(f"        outline median {median_length:.1f} x {median_width:.1f} mm vs {ref_length} x {ref_width} "
          f"({percent(median_length, ref_length)} / {percent(median_width, ref_width)})"
          f"{'  (not meaningful: outline far from a rectangle)' if table['outline']['rectangle_fill_ratio'] < MIN_FILL_FOR_MEDIAN else ''}")
    references = [(h, h) if isinstance(h, (int, float)) else h for h in measured["holes"]]
    holes = sorted(table["holes"], key=lambda h: -h["diameter_mm"])  # largest first, like the hand list
    for hole, (ref_l, ref_w) in zip(holes, references):
        hole_l, hole_w = hole_size(hole)
        print(f"        hole ({hole['shape']}) {hole_l:.1f} x {hole_w:.1f} mm vs {ref_l} x {ref_w} "
              f"({percent(hole_l, ref_l)} / {percent(hole_w, ref_w)})")
    if len(holes) != len(references):
        print(f"        {len(holes)} holes measured, hand list has {len(references)}")


def main(names):
    for name in names or PARTS:
        config = PARTS[name]
        base_out = Path(config.get("out", OUT / name))
        for index, photo in enumerate(config["photos"], start=1):
            out = base_out if len(config["photos"]) == 1 else base_out.with_name(f"{base_out.name}_{index}")
            result = run_photo(name, PHOTO_DIR / photo["file"], photo["click"], out, config["candidates"],
                               config.get("candidates_folder", "candidates_intent"),
                               suggest=config.get("suggest", True))
            card_px, medians = extra_measurements(out, result["hole_method"])
            compare(f"{name} ({photo['file']})", config["measured"], result["table"], card_px, medians)
            (out / "3_report_extras.json").write_text(json.dumps(
                {"card_long_px": round(card_px, 1), "median_length_mm": round(medians[0], 2),
                 "median_width_mm": round(medians[1], 2), "measured": config["measured"]}, indent=1),
                encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
