"""Run the pipeline on synthetic photos of broken parts, then ask Muse Wonder for a completion.

The intact design of every broken part is known (parts/broken_parts.py), so the report says how close
the suggestion comes to it: the top-view IoU against the true design before (the winner, which
follows the broken photo) and after the completion, and the outline and holes against the design.
Outputs in outputs/e2e/<name>/ (6_completion/ for the suggestion) and outputs/e2e/broken_report.json.

Run: .venv\\Scripts\\python.exe run_broken_scenes.py [A_chipped A_half_hole A_missing_hole D_tab_broken]
"""
import json
import sys
from pathlib import Path

import numpy as np

import usage_ledger
from completion import FOLDER, suggest_completion
from e2e_pipeline import MM_PER_PIXEL, SCALE, run_scene, save_json
from iou import aligned_iou
from part_measurements import measure_part
from parts.broken_parts import BROKEN, design_truth, make_broken_part
from parts.template_parts import make_part
from render_silhouette import render_top_silhouette
from repair import make_client
from synthetic_scene import LIGHT_METAL, make_scene
from webapp.builder import Builder

OUT = Path("outputs") / "e2e"


def against_design(mask, design_mask, truth):
    """A silhouette compared with the intact design: IoU, outline and holes."""
    table = measure_part(mask, SCALE)
    holes = sorted(h["diameter_mm"] for h in table["holes"])
    true_holes = sorted(h["diameter_mm"] for h in truth["holes"])
    return {"iou_vs_design": round(aligned_iou(design_mask, MM_PER_PIXEL, mask, MM_PER_PIXEL).iou, 4),
            "outline_mm": [table["outline"]["length_mm"], table["outline"]["width_mm"]],
            "design_outline_mm": [truth["length"], truth["width"]],
            "hole_diameters_mm": holes, "design_hole_diameters_mm": true_holes,
            "hole_count_matches": len(holes) == len(true_holes)}


def run(name, builder, client):
    out = OUT / name
    workplane = make_broken_part(name)
    photo, masks = make_scene(workplane, LIGHT_METAL)
    result = run_scene(name, photo, masks, None, workplane, out, 10)
    summary = result["candidates"]
    row = summary["result"]
    report = {"part": name, "damage": BROKEN[name]["damage"], "result_source": summary["result_source"]}
    if not row:
        return {**report, "error": "no result program to complete"}
    winner_path = Path(row["file"])
    winner_mask = np.load(winner_path.with_suffix(".default.mask.npy"))
    completion = suggest_completion(out, winner_path, winner_mask, builder, client)
    truth = design_truth(name)
    design_mask = render_top_silhouette(make_part(BROKEN[name]["design"]), MM_PER_PIXEL) > 0
    report.update({"winner": winner_path.name, "before": against_design(winner_mask, design_mask, truth),
                   "completion": completion})
    if completion and completion["program"]:
        mask, error = builder.silhouette(out / FOLDER / completion["program"], MM_PER_PIXEL)
        report["after"] = against_design(mask, design_mask, truth) if error is None else {"error": error}
    usage = usage_ledger.summarize(out)
    report["usage"] = usage
    save_json(out / FOLDER / "report.json", report) if completion else None
    return report


def main(names):
    builder, client = Builder(), make_client()
    try:
        reports = [run(name, builder, client) for name in (names or BROKEN)]
    finally:
        builder.close()
    save_json(OUT / "broken_report.json", reports)
    print("\npart            cues -> suggestion valid  IoU vs design before -> after  holes match  Wonder s  cost")
    for r in reports:
        c = r.get("completion") or {}
        wonder = r["usage"]["models"].get(usage_ledger.WONDER, {}) if "usage" in r else {}
        print(f"{r['part']:15s} {str(bool(c)):5s} -> {str(c.get('valid')):5s}            "
              f"{r.get('before', {}).get('iou_vs_design')} -> {r.get('after', {}).get('iou_vs_design')}"
              f"            {r.get('after', {}).get('hole_count_matches')}       {wonder.get('seconds')}  "
              f"${(wonder.get('cost_usd') or 0):.3f}")
        print(f"    suggestion: {c.get('suggestion')}")


if __name__ == "__main__":
    main(sys.argv[1:])
