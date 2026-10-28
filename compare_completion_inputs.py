"""Compare completion suggestions made from the rectified photo and from the part's mask only.

For every synthetic broken part already run by run_broken_scenes.py, asks Muse Wonder twice with the
same winner and cues: once with the photo (6_completion_photo/) and once with only the mask
(6_completion_mask/), and compares both with the true design. The chosen input's result is copied to
6_completion/, which the web app shows. Report: outputs/e2e/completion_inputs_report.json.

Run: .venv\\Scripts\\python.exe compare_completion_inputs.py [photo|mask]   (the input to show; default: the closer one)
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from completion import FOLDER, suggest_completion
from e2e_pipeline import MM_PER_PIXEL, save_json
from parts.broken_parts import BROKEN, design_truth
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette
from repair import make_client
from run_broken_scenes import OUT, against_design
from webapp.builder import Builder

INPUTS = ("photo", "mask")


def compare(name, builder, client):
    out = OUT / name
    summary = json.loads((out / "5_summary_candidates_arcs_effort_medium.json").read_text(encoding="utf-8"))
    winner_path = Path(summary["result"]["file"])
    winner_mask = np.load(winner_path.with_suffix(".default.mask.npy"))
    design_mask = render_top_silhouette(make_part(BROKEN[name]["design"]), MM_PER_PIXEL) > 0
    truth = design_truth(name)
    row = {"part": name, "before": against_design(winner_mask, design_mask, truth)["iou_vs_design"]}
    for source in INPUTS:
        folder = f"{FOLDER}_{source}"
        result = suggest_completion(out, winner_path, winner_mask, builder, client, source=source, folder_name=folder)
        after = None
        if result and result["program"]:
            mask, error = builder.silhouette(out / folder / result["program"], MM_PER_PIXEL)
            after = against_design(mask, design_mask, truth) if error is None else {"error": error}
        usage = result.get("usage") or {}
        row[source] = {"valid": result["valid"], "suggestion": result["suggestion"], "parts": result["parts"],
                       "after": after, "seconds": result["seconds"],
                       "cost_usd": round(usage.get("prompt_tokens", 0) * 4e-6 + usage.get("completion_tokens", 0) * 20e-6, 4)}
    return row


def main(arguments):
    builder, client = Builder(), make_client()
    try:
        rows = [compare(name, builder, client) for name in BROKEN]
    finally:
        builder.close()
    gaps = [r["photo"]["after"]["iou_vs_design"] - r["mask"]["after"]["iou_vs_design"]
            for r in rows if r["photo"]["after"] and r["mask"]["after"] and "iou_vs_design" in r["photo"]["after"]
            and "iou_vs_design" in r["mask"]["after"]]
    # Decision rule from the consultation: the mask becomes the default if it is about as good (small difference).
    chosen = arguments[0] if arguments else ("mask" if gaps and max(gaps) <= 0.01 and
                                             all(r["mask"]["valid"] for r in rows) else "photo")
    for r in rows:  # the web app reads 6_completion/
        target = OUT / r["part"] / FOLDER
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(OUT / r["part"] / f"{FOLDER}_{chosen}", target)
    save_json(OUT / "completion_inputs_report.json", {"rows": rows, "photo_minus_mask_iou": gaps, "chosen": chosen})

    print("\npart             before  | photo: valid  after   parts (m/e/o)  cost   | mask: valid  after   parts (m/e/o)  cost")
    for r in rows:
        cells = []
        for source in INPUTS:
            s = r[source]
            kinds = [p["basis"] for p in s["parts"]]
            counts = "/".join(str(kinds.count(k)) for k in ("measured", "estimated", "optional"))
            cells.append(f"{str(s['valid']):5s}  {(s['after'] or {}).get('iou_vs_design')!s:6s}  {counts:13s}  ${s['cost_usd']:.3f}")
        print(f"{r['part']:16s} {r['before']:.4f}  | {cells[0]}  | {cells[1]}")
    print(f"photo minus mask IoU after completion: {[round(g, 4) for g in gaps]} -> shown: {chosen}")


if __name__ == "__main__":
    main(sys.argv[1:])
