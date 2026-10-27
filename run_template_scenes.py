"""Run the end-to-end pipeline on synthetic scenes of the template parts.

A_light / A_dark: the 80 x 40 plate as light metal and as a dark part, to compare
the hole methods (no candidates). B, C, D: structurally different parts with
10 candidates each. Outputs go to outputs/e2e/<scene>/.

Run all:   .venv\\Scripts\\python.exe run_template_scenes.py
Run some:  .venv\\Scripts\\python.exe run_template_scenes.py B C
"""
import sys
from pathlib import Path

from e2e_pipeline import run_scene
from parts.template_parts import make_part, part_truth
from synthetic_scene import DARK_PART, LIGHT_METAL, make_scene

OUT = Path("outputs") / "e2e"
SCENES = {
    "A_light": {"part": "A", "color": LIGHT_METAL, "candidates": 0},
    "A_dark": {"part": "A", "color": DARK_PART, "candidates": 0},
    "B": {"part": "B", "color": LIGHT_METAL, "candidates": 10},
    "C": {"part": "C", "color": LIGHT_METAL, "candidates": 10},
    "D": {"part": "D", "color": LIGHT_METAL, "candidates": 10},
}


def main(names):
    for name in names or SCENES:
        config = SCENES[name]
        workplane = make_part(config["part"])
        photo, masks = make_scene(workplane, config["color"])
        run_scene(name, photo, masks, part_truth(config["part"]), workplane, OUT / name, config["candidates"])


if __name__ == "__main__":
    main(sys.argv[1:])
