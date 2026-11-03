"""Run the end-to-end pipeline on template parts A, C, D, E in four painted appearances.

Same settings as run_template_scenes.py (10 candidates, medium reasoning effort, simulated
click, repair when no candidate passes): only the part's surface differs — background, card,
tilt, blur and noise are shared with the default scene (see synthetic_appearance.py).
Outputs go to outputs/e2e/<part>_<appearance>/, and the per-scene table to
outputs/e2e/appearance_table.json. A scene that raises (e.g. SAM finds nothing) is recorded
as a failed row, never dropped. Stops early if the projected total would exceed the budget.

Run all:   .venv\\Scripts\\python.exe run_appearance_scenes.py
Run some:  .venv\\Scripts\\python.exe run_appearance_scenes.py A_brushed D_wood
"""
import json
import sys
import traceback
from pathlib import Path

from candidates import DEFAULT_REASONING_EFFORT
from e2e_pipeline import MM_PER_PIXEL, aligned_iou, run_scene
from parts.template_parts import make_part, part_truth
from render_silhouette import render_top_silhouette
from run_candidate import run_candidate
from synthetic_appearance import APPEARANCES
from synthetic_scene import make_scene
from usage_ledger import summarize as summarize_usage

OUT = Path("outputs") / "e2e"
PARTS = ("A", "C", "D", "E")
CANDIDATE_COUNT = 10
COST_BUDGET_USD = 4.0


def _sam_result(run_dir):
    """(found, source, confidence) for the part from the saved SAM attempts."""
    path = run_dir / "2_sam_attempts.json"
    if not path.exists():
        return False, None, None
    attempts = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(attempts, list):  # no part found: only the attempts list was saved
        return False, None, None
    source = attempts["chosen_source"]
    confidences = [c for a in attempts["attempts"] if a.get("object") == "part"
                   and a.get("source", "name") == source for c in a["confidences"]]
    return True, source, max(confidences) if confidences else None


def _measurement_result(run_dir, truth):
    """Outline/hole errors of the chosen hole method against the truth (all saved)."""
    saved = json.loads((run_dir / "3_measurements.json").read_text(encoding="utf-8"))
    method = saved["chosen_method"]
    table = saved["table"]
    errors = saved["errors_vs_truth"][method]
    matched = [h for h in errors["holes"] if h["center_error_mm"] is not None]
    return {
        "hole_method": method, "holes_found": table["hole_count"], "holes_true": len(truth["holes"]),
        "length_error_pct": round(100 * errors["length_mm"] / truth["length"], 2),
        "width_error_pct": round(100 * errors["width_mm"] / truth["width"], 2),
        "hole_diameter_error_mm": round(max(abs(h["diameter_error_mm"]) for h in matched), 3) if matched else None,
        "hole_center_error_mm": round(max(h["center_error_mm"] for h in matched), 3) if matched else None,
        "hole_shapes": [(h["true_shape"], h["measured_shape"]) for h in errors["holes"]],
        "mask_iou_vs_truth": (saved["mask_iou_vs_truth"] or {}).get(method),
    }


def _result_vs_truth_iou(result_file, truth_workplane):
    """IoU of the result program against the true design (None when it does not build)."""
    if not result_file:
        return None, "no result program"
    mask, error = run_candidate(result_file, MM_PER_PIXEL)
    if error or mask is None or not mask.any():
        return None, error or "empty part"
    truth_mask = render_top_silhouette(truth_workplane, MM_PER_PIXEL) > 0
    return round(aligned_iou(truth_mask, MM_PER_PIXEL, mask, MM_PER_PIXEL).iou, 4), None


def scene_row(name, part, appearance, run_dir, truth, truth_workplane, failure=None):
    """Item-3 row for one scene, from its saved files (failures included)."""
    row = {"scene": name, "part": part, "appearance": appearance}
    found, source, confidence = _sam_result(run_dir)
    row.update({"sam_found": found, "sam_source": source, "sam_confidence": confidence})
    if failure is not None:
        row["failed"] = failure
        try:
            row["cost_usd"] = summarize_usage(run_dir)["known_cost_usd"]
        except OSError:
            row["cost_usd"] = 0.0
        return row
    row.update(_measurement_result(run_dir, truth))
    summaries = sorted(run_dir.glob("5_summary_*.json"))
    summary = json.loads(summaries[-1].read_text(encoding="utf-8"))
    repair = summary.get("repair")
    row.update({
        "compiled": f"{summary['compiled']}/{summary['candidate_count']}",
        "correct_topology": summary["correct_topology"],
        "result_source": summary["result_source"],
        "repair_used": bool(repair),
        "repair_rounds": [r["round"] for r in repair["rounds"]] if repair else [],
        "repair_passed": repair["passed"] if repair else None,
        "iou_vs_mask": (summary["result"] or {}).get("iou"),
        "iou_ceiling": summary["iou_ceiling"],
        "cost_usd": summary["usage"]["known_cost_usd"],
    })
    iou, error = _result_vs_truth_iou((summary["result"] or {}).get("file"), truth_workplane)
    row["iou_vs_design"] = iou
    if error:
        row["iou_vs_design_error"] = error
    return row


def main(arguments):
    effort = next((a.split("=", 1)[1] for a in arguments if a.startswith("--effort=")), DEFAULT_REASONING_EFFORT)
    folder = "candidates_arcs" if effort == "model-default" else f"candidates_arcs_effort_{effort}"
    effort = None if effort == "model-default" else effort
    wanted = [a for a in arguments if not a.startswith("--")]
    names = [f"{part}_{appearance}" for part in PARTS for appearance in APPEARANCES]
    names = [n for n in names if not wanted or n in wanted]
    path = OUT / "appearance_table.json"
    previous = {r["scene"]: r for r in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    prior = [r for scene, r in previous.items() if scene not in names]
    spent = round(sum(r.get("cost_usd") or 0.0 for r in prior), 4)
    worst_by_part = {}
    for row in prior:
        cost = row.get("cost_usd") or 0.0
        worst_by_part[row["part"]] = max(worst_by_part.get(row["part"], 0.0), cost)
    rows = []
    for position, name in enumerate(names):
        part = next(p for p in PARTS if name.startswith(p + "_"))
        appearance = name[len(part) + 1:]
        workplane, truth, run_dir = make_part(part), part_truth(part), OUT / name
        failure = None
        try:
            photo, masks = make_scene(workplane, appearance=appearance)
            run_scene(name, photo, masks, truth, workplane, run_dir, CANDIDATE_COUNT,
                      candidates_folder=folder, reasoning_effort=effort)
        except Exception as exc:  # noqa: BLE001 (a failed scene is a reported row, not a crash)
            failure = {"stage": "pipeline", "error": f"{type(exc).__name__}: {exc}",
                       "traceback_tail": traceback.format_exc(limit=3).strip().splitlines()[-1]}
            print(f"    SCENE FAILED: {failure['error']}")
        row = scene_row(name, part, appearance, run_dir, truth, workplane, failure)
        rows.append(row)
        scene_cost = row.get("cost_usd") or 0.0
        spent = round(spent + scene_cost, 4)
        worst_by_part[part] = max(worst_by_part.get(part, 0.0), scene_cost)
        ceiling = max(worst_by_part.values())
        # Conservative projection: every remaining scene at its own part's worst so far
        # (parts not seen yet at the global worst). Still an overestimate, but per-part.
        projection = spent + sum(worst_by_part.get(next(p for p in PARTS if n.startswith(p + "_")), ceiling)
                                 for n in names[position + 1:])
        remaining = len(names) - position - 1
        print(f"    scene cost ${scene_cost:.4f}, spent ${spent:.4f} "
              f"(worst by part {worst_by_part}, {remaining} left)")
        if projection > COST_BUDGET_USD:
            print(f"    STOPPING: projected total ${projection:.2f} exceeds "
                  f"the ${COST_BUDGET_USD:.2f} budget")
            break
    previous.update({row["scene"]: row for row in rows})
    path.write_text(json.dumps(list(previous.values()), indent=2), encoding="utf-8")
    print(f"\n{len(rows)} scene(s), spent ${spent:.4f}; table saved to {path}")


if __name__ == "__main__":
    main(sys.argv[1:])
