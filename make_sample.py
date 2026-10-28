"""Copy a saved run into samples/ in a compact form, so a fresh clone can replay it without API keys.

Keeps only what the web app's replay reads; the photo becomes a high-quality JPEG and the
candidate silhouettes PNGs (the replay reads the saved masks, not the photo, for measurements).
Only synthetic scenes belong here: real photos show the user's card.

Muse Wonder repair rounds and a completion suggestion are kept when the run has them (their
programs, silhouettes, results and the material a completion adds), and so is the usage ledger.

Run: .venv\\Scripts\\python.exe make_sample.py A_light A_light_repair D_tab_broken
"""
import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from webapp.replay import RUNS_DIR, SAMPLES_DIR, candidate_round

FILES = ["2_sam_attempts.json", "3_measurements.json", "3_mask_card.png", "3_part_mask_topdown.png"]


def make_sample(name):
    source = RUNS_DIR / name
    if not name[0].isupper():  # template scenes are named after their part (A_light, B, ...); real photos are not
        raise SystemExit(f"{name!r} does not look like a synthetic scene; samples must not contain real photos")
    target = SAMPLES_DIR / name
    shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True)
    photo = cv2.imread(str(source / "1_scene.png"))
    cv2.imwrite(str(target / "1_scene.jpg"), photo, [cv2.IMWRITE_JPEG_QUALITY, 92])
    method = json.loads((source / "3_measurements.json").read_text(encoding="utf-8"))["chosen_method"]
    for file in FILES + [f"3_mask_{method}.png"]:
        shutil.copy(source / file, target / file)
    round_name = candidate_round(name)
    shutil.copy(source / f"5_summary_{round_name}.json", target / f"5_summary_{round_name}.json")
    (target / round_name).mkdir()
    for program in (source / round_name).glob("cand_*.py"):
        shutil.copy(program, target / round_name / program.name)
        mask_path = program.with_suffix(".default.mask.npy")
        if mask_path.exists():
            cv2.imwrite(str(target / round_name / f"{program.stem}.default.mask.png"),
                        np.load(mask_path).astype(np.uint8) * 255)
    shutil.copy(source / round_name / "baseline.py", target / round_name / "baseline.py")
    if (source / "usage.jsonl").exists():
        shutil.copy(source / "usage.jsonl", target / "usage.jsonl")
    for repair in source.glob("repair_round_*"):  # Muse Wonder repairs: program, silhouette, result
        (target / repair.name).mkdir()
        for file in ("repaired.py", "result.json"):
            if (repair / file).exists():
                shutil.copy(repair / file, target / repair.name / file)
        mask_path = repair / "repaired.default.mask.npy"
        if mask_path.exists():
            cv2.imwrite(str(target / repair.name / "repaired.default.mask.png"), np.load(mask_path).astype(np.uint8) * 255)
    completion = source / "6_completion"
    if completion.exists():  # the completion suggestion, without the images sent to Muse Wonder
        (target / completion.name).mkdir()
        for file in ("completion.json", "completed.py", "added.stl", "removed.stl", "compare.json"):
            if (completion / file).exists():
                shutil.copy(completion / file, target / completion.name / file)
    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"sample {target}: {size / 1e6:.2f} MB")


if __name__ == "__main__":
    for run in sys.argv[1:] or ["A_light"]:
        make_sample(run)
