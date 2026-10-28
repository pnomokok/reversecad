"""Make a saved run that shows the repair loop: scene A_light with only deliberately broken candidates.

Copies A_light's photo, masks and measurements into outputs/e2e/A_light_repair/, writes a candidate
round holding just the broken programs (a hole moved 4 mm, a corner cut 8 mm, repair_inputs.py),
and validates it like any run: no candidate passes, so Muse Wonder repairs (1-2 calls). The run
replays in the web app and can be packed into samples/ with make_sample.py.

Run: .venv\\Scripts\\python.exe make_repair_run.py
"""
import json
import shutil

import cv2

import usage_ledger
from baseline_cad import baseline_code
from e2e_pipeline import validate
from parts.template_parts import make_part, part_truth
from repair_inputs import write_broken_candidates
from webapp.replay import RUNS_DIR

SOURCE, NAME, ROUND = "A_light", "A_light_repair", "candidates_arcs_effort_medium"
FILES = ["1_scene.png", "1_truth.json", "2_sam_attempts.json", "3_measurements.json", "3_mask_card.png",
         "3_part_mask_topdown.png"]


def main():
    source, out = RUNS_DIR / SOURCE, RUNS_DIR / NAME
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    measurements = json.loads((source / "3_measurements.json").read_text(encoding="utf-8"))
    for file in FILES + [f"3_mask_{measurements['chosen_method']}.png"]:
        shutil.copy(source / file, out / file)
    table = measurements["table"]
    folder = out / ROUND
    entries = []
    for i, (fault, path) in enumerate(write_broken_candidates(folder, table), 1):
        program = folder / f"cand_{i}.py"
        path.rename(program)
        entries.append((program, None))
    baseline = folder / "baseline.py"
    baseline.write_text(baseline_code(table), encoding="utf-8")
    reference = cv2.imread(str(out / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0
    summary = validate(out, ROUND, entries, baseline, reference, part_truth("A"), make_part("A"), table)
    print(f"result: {summary['result_source']}; repair passed: {(summary['repair'] or {}).get('passed')}")
    for line in usage_ledger.describe(usage_ledger.summarize(out)):
        print("  ", line)


if __name__ == "__main__":
    main()
