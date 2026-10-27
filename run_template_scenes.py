"""Run the end-to-end pipeline on synthetic scenes of the template parts.

A_dark: the 80 x 40 plate as a dark part, to compare the hole methods (no
candidates). A, B, C, D: light parts with 10 candidates each, the baseline and
the design-intent test. The part is picked by a simulated click (SAM point
prompt); finding it by name is the fallback. Outputs go to outputs/e2e/<scene>/,
and a comparison table of all scenes to outputs/e2e/design_intent_table.json.

Run all:   .venv\\Scripts\\python.exe run_template_scenes.py
Run some:  .venv\\Scripts\\python.exe run_template_scenes.py B C
Reasoning effort:  .venv\\Scripts\\python.exe run_template_scenes.py A_light B C D --effort=low
"""
import json
import sys
from pathlib import Path

from candidates import DEFAULT_REASONING_EFFORT
from e2e_pipeline import run_scene
from parts.template_parts import make_part, part_truth
from synthetic_scene import DARK_PART, LIGHT_METAL, make_scene

OUT = Path("outputs") / "e2e"
SCENES = {
    "A_light": {"part": "A", "color": LIGHT_METAL, "candidates": 10},
    "A_dark": {"part": "A", "color": DARK_PART, "candidates": 0},
    "B": {"part": "B", "color": LIGHT_METAL, "candidates": 10},
    "C": {"part": "C", "color": LIGHT_METAL, "candidates": 10},
    "D": {"part": "D", "color": LIGHT_METAL, "candidates": 10},
    "E": {"part": "E", "color": LIGHT_METAL, "candidates": 10},
}


def table_row(name, result):
    summary = result["candidates"]
    row = {"scene": name, "part_found_by": result["part_found_by"], "hole_method": result["hole_method"],
           "correct_topology": f"{summary['correct_topology']}/{summary['candidate_count']}"}
    for label in ("winner", "baseline"):
        program = summary[label] or {}
        intent = program.get("design_intent", {})
        row[label] = {"iou": program.get("iou"), "topology_ok": program.get("topology_ok"),
                      "parameters": intent.get("parameter_count"),
                      "hole_diameter_linked": intent.get("hole_diameter_linked"),
                      "length_parameter": intent.get("length_parameter"),
                      "symmetric_after_length_change": intent.get("symmetric_after_length_change"),
                      "edge_margin_kept": intent.get("edge_margin_kept"),
                      "file": program.get("file")}
    return row


def main(arguments):
    # --effort=low|medium|... sets Muse Spark Open's reasoning effort (default medium); candidates go to
    # their own folder. --effort=model-default sends no setting (saved as candidates_arcs/).
    effort = next((a.split("=", 1)[1] for a in arguments if a.startswith("--effort=")), DEFAULT_REASONING_EFFORT)
    names = [a for a in arguments if not a.startswith("--")]
    if effort == "model-default":
        effort, folder = None, "candidates_arcs"
    else:
        folder = f"candidates_arcs_effort_{effort}"
    rows = []
    for name in names or SCENES:
        config = SCENES[name]
        workplane = make_part(config["part"])
        photo, masks = make_scene(workplane, config["color"])
        result = run_scene(name, photo, masks, part_truth(config["part"]), workplane, OUT / name,
                           config["candidates"], candidates_folder=folder, reasoning_effort=effort)
        if config["candidates"]:
            rows.append(table_row(name, result))
    if rows:
        path = OUT / "design_intent_table.json"
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        merged = {row["scene"]: row for row in previous + rows}  # keep scenes not run this time
        path.write_text(json.dumps(list(merged.values()), indent=2), encoding="utf-8")
        print(f"\ncomparison table saved to {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
