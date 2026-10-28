"""Make saved runs that show the repair loop and the "no candidate passed" state, for replay and samples/.

  A_light_repair:   scene A_light with only deliberately broken candidates (a hole moved 4 mm, a corner
                    cut 8 mm, repair_inputs.py); no candidate passes, so Muse Wonder repairs (1-2 calls).
  A_torn_fallback:  a synthetic A plate with torn edges (parts/broken_parts.py, A_torn), the same broken
                    candidates and the repair switched off: the result is the measured shape, and the app
                    says the edges are irregular. Needs only SAM for the scene (3 calls), no Muse model.

Run: .venv\\Scripts\\python.exe make_repair_run.py [A_light_repair] [A_torn_fallback]
"""
import json
import shutil
import sys

import cv2

import usage_ledger
from baseline_cad import baseline_code
from e2e_pipeline import run_scene, validate
from parts.broken_parts import make_broken_part
from parts.template_parts import make_part, part_truth
from repair_inputs import write_broken_candidates
from synthetic_scene import LIGHT_METAL, make_scene
from webapp.replay import RUNS_DIR

ROUND = "candidates_arcs_effort_medium"
FILES = ["1_scene.png", "2_sam_attempts.json", "3_measurements.json", "3_mask_card.png", "3_part_mask_topdown.png"]


def copy_measured_scene(source, out):
    """Photo, masks and measurements of an already measured scene."""
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    measurements = json.loads((source / "3_measurements.json").read_text(encoding="utf-8"))
    for file in FILES + [f"3_mask_{measurements['chosen_method']}.png"]:
        shutil.copy(source / file, out / file)
    return measurements["table"]


def broken_round(out, table, truth, truth_workplane, repair):
    """Validate a round holding only the deliberately broken candidates."""
    folder = out / ROUND
    entries = []
    for i, (fault, path) in enumerate(write_broken_candidates(folder, table), 1):
        program = folder / f"cand_{i}.py"
        path.rename(program)
        entries.append((program, None))
    baseline = folder / "baseline.py"
    baseline.write_text(baseline_code(table), encoding="utf-8")
    reference = cv2.imread(str(out / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0
    summary = validate(out, ROUND, entries, baseline, reference, truth, truth_workplane, table, repair=repair)
    print(f"{out.name}: {summary['result_source']}; repair: {(summary['repair'] or {}).get('passed')}")
    for line in usage_ledger.describe(usage_ledger.summarize(out)):
        print("  ", line)


def repair_run():
    out = RUNS_DIR / "A_light_repair"
    table = copy_measured_scene(RUNS_DIR / "A_light", out)
    shutil.copy(RUNS_DIR / "A_light" / "1_truth.json", out / "1_truth.json")
    broken_round(out, table, part_truth("A"), make_part("A"), repair=True)


def fallback_run():
    out = RUNS_DIR / "A_torn_fallback"
    shutil.rmtree(out, ignore_errors=True)
    workplane = make_broken_part("A_torn")
    photo, masks = make_scene(workplane, LIGHT_METAL)
    run_scene("A_torn_fallback", photo, masks, None, workplane, out, 0)  # SAM and measurements only
    table = json.loads((out / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    broken_round(out, table, None, workplane, repair=False)


if __name__ == "__main__":
    runs = {"A_light_repair": repair_run, "A_torn_fallback": fallback_run}
    for name in sys.argv[1:] or runs:
        runs[name]()
