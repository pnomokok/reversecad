"""Run the pipeline on real photos in data/private and compare with ruler measurements.

Each photo has a card for scale; the part is picked by a click (pixel chosen by
looking at the photo). Ruler values are the user's: outline length x width and
each hole's length x width (a round hole has length = width). Outputs go to
outputs/real/<photo>/ (git-ignored; they show the card).

Run all:   .venv\\Scripts\\python.exe run_real_photos.py
Run some:  .venv\\Scripts\\python.exe run_real_photos.py carton
"""
import sys
from pathlib import Path

from e2e_pipeline import run_photo

PHOTO_DIR = Path("data") / "private"
OUT = Path("outputs") / "real"
PHOTOS = {
    # Earlier rounds: candidates_intent/ (no code, stuck on the torn edge), candidates_clean/ (clean shapes allowed).
    "carton": {"file": "carton_with_card.jpeg", "click": (550, 980), "candidates": 10,
               "candidates_folder": "candidates_kit",
               "ruler_outline": (188, 91), "ruler_holes": [(20, 8), (13, 7)]},
    "key": {"file": "key_with_card.jpeg", "click": (480, 1103), "candidates": 0,  # outline out of scope
            "ruler_outline": (57, 22.5), "ruler_holes": [(12, 6)]},
    # Stress test: the pockets are blind cavities under clear plastic domes, not through-holes.
    # The user asked that this photo never leaves data/private (only SAM may see it): outputs stay there
    # and no prompt suggestions are requested.
    "blister": {"file": "drug_with_card.jpeg", "click": (720, 1080), "candidates": 0,
                "ruler_outline": (70.5, 52), "ruler_holes": [(23, 23)] * 4,
                "out": PHOTO_DIR / "blister_run", "suggest": False},
}


def hole_size(hole):
    if hole["shape"] == "circle":
        return hole["diameter_mm"], hole["diameter_mm"]
    return hole["length_mm"], hole["width_mm"]  # for a polygon: its bounding rectangle


def compare_with_ruler(name, config, table):
    length, width = table["outline"]["length_mm"], table["outline"]["width_mm"]
    ruler_length, ruler_width = config["ruler_outline"]
    print(f"\n[ruler] {name}: outline {length:.1f} x {width:.1f} mm vs ruler {ruler_length} x {ruler_width} "
          f"({(length - ruler_length) / ruler_length:+.1%} / {(width - ruler_width) / ruler_width:+.1%})")
    measured = sorted(table["holes"], key=lambda h: -h["diameter_mm"])  # largest first, like the ruler list
    for hole, (ruler_l, ruler_w) in zip(measured, config["ruler_holes"]):
        hole_l, hole_w = hole_size(hole)
        print(f"        hole ({hole['shape']}) {hole_l:.1f} x {hole_w:.1f} mm vs ruler {ruler_l} x {ruler_w} "
              f"({(hole_l - ruler_l) / ruler_l:+.1%} / {(hole_w - ruler_w) / ruler_w:+.1%})")
    if len(measured) != len(config["ruler_holes"]):
        print(f"        {len(measured)} holes measured, ruler lists {len(config['ruler_holes'])}")


def main(names):
    for name in names or PHOTOS:
        config = PHOTOS[name]
        result = run_photo(name, PHOTO_DIR / config["file"], config["click"], config.get("out", OUT / name),
                           config["candidates"], config.get("candidates_folder", "candidates_intent"),
                           suggest=config.get("suggest", True))
        compare_with_ruler(name, config, result["table"])


if __name__ == "__main__":
    main(sys.argv[1:])
