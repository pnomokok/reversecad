"""The large synthetic test: random parts (parts/random_parts.py) through the whole pipeline, against their design.

Per part: synthetic photo -> SAM (card, click) -> measurements -> up to CANDIDATES candidates from Muse
Spark Open, PARALLEL_REQUESTS at a time, stopping once three that pass every check build the same shape
-> builds on Modal (modal_render.py) -> winner, or Muse Wonder repair -> Muse Wonder completion when break
cues exist -> the final model compared with the part's true design. PARTS_AT_ONCE parts run together.

Budget guard: no new part starts once the model costs reach BUDGET_USD, or when, after 30 parts, the
average cost per part projects past it. Every REPORT_EVERY parts an interim report is written
(outputs/random_test/interim_<n>.json) and printed as a line starting with INTERIM. A part that already
has its report.json is not run again (resume after a stop).

Run: .venv\\Scripts\\python.exe run_random_parts.py [count] [--local]   (--local: build in local processes)
"""
import json
import math
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

import cv2
import numpy as np

import usage_ledger
from baseline_cad import baseline_code
from candidates import extract_python_block, iter_candidates
from completion import suggest_completion
from e2e_pipeline import MM_PER_PIXEL, SCALE, check_program, run_scene, save_json, search_settled, validate
from iou import aligned_iou
from measure import CARD_LONG_MM
from model_view import model_view
from part_measurements import check_topology, measure_part
from parts.random_parts import make_random_part, random_part, truth_of
from render_silhouette import render_top_silhouette
from repair import make_client
from run_candidate import run_candidate
from synthetic_scene import LIGHT_METAL, make_scene
from webapp.builder import Builder

OUT = Path("outputs") / "random_test"
ROUND = "candidates_arcs_effort_medium"
CANDIDATES, PARALLEL_REQUESTS, PARTS_AT_ONCE = 5, 3, 8
BUDGET_USD, PROJECTION_AFTER, REPORT_EVERY = 45.0, 30, 50
FOUND = ("candidate", "repair · Muse Wonder")


def placement(part):
    """Where the part lies in the synthetic scene: just right of the card, its rotated box clear of it."""
    xs = [x for x, _ in part["spec"]["outline"]]
    ys = [y for _, y in part["spec"]["outline"]]
    angle = math.radians(8)
    half = ((max(xs) - min(xs)) * math.cos(angle) + (max(ys) - min(ys)) * math.sin(angle)) / 2
    return CARD_LONG_MM + 6 + half, 27.0


def search(out, table, reference, truth, render):
    """Up to CANDIDATES candidates, checked as they arrive; stops once the search has settled."""
    folder = out / ROUND
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    requests = iter_candidates(model_view(table), out / "3_part_mask_topdown.png", CANDIDATES,
                               max_parallel=PARALLEL_REQUESTS)
    for prompt, index, response in requests:
        (folder / f"cand_{index}_prompt.txt").write_text(prompt, encoding="utf-8")
        save_json(folder / f"cand_{index}_response.json", response)
        usage_ledger.record_response(out, usage_ledger.SPARK_OPEN, f"candidate {index}", response)
        path = folder / f"cand_{index}.py"
        if "error" in response:
            row = {"file": str(path), "error": f"request failed: {response['error']}"}
        else:
            code = extract_python_block(response["choices"][0]["message"]["content"])
            if code is None:
                row = {"file": str(path), "error": f"no python code block (finish={response['choices'][0]['finish_reason']})"}
            else:
                path.write_text(code, encoding="utf-8")
                row = check_program(path, reference, truth, table, render=render)
        rows.append({"candidate": index, "style": response.get("style"), **row})
        if search_settled(rows):
            requests.close()
            break
    return rows


def against_design(mask, part):
    """The final model's silhouette against the part's intact design."""
    design = truth_of(part, "design")
    design_mask = render_top_silhouette(make_random_part(part, "design"), MM_PER_PIXEL) > 0
    table = measure_part(mask, SCALE)
    topology_ok, issues = check_topology(table, design)
    holes, true_holes = sorted(h["diameter_mm"] for h in table["holes"]), sorted(h["diameter_mm"] for h in design["holes"])
    return {"iou_vs_design": round(aligned_iou(design_mask, MM_PER_PIXEL, mask, MM_PER_PIXEL).iou, 4),
            "topology_ok": topology_ok, "topology_issues": issues,
            "length_error_pct": round(100 * (table["outline"]["length_mm"] - design["length"]) / design["length"], 2),
            "width_error_pct": round(100 * (table["outline"]["width_mm"] - design["width"]) / design["width"], 2),
            "hole_count": [len(holes), len(true_holes)],
            "hole_diameter_error_mm": round(max((abs(a - b) for a, b in zip(holes, true_holes)), default=0), 3)
            if len(holes) == len(true_holes) else None}


def run_part(seed, render, builder, client):
    part = random_part(seed)
    out = OUT / part["name"]
    if (out / "report.json").exists():
        return json.loads((out / "report.json").read_text(encoding="utf-8"))
    started = time.perf_counter()
    workplane = make_random_part(part)
    photo, masks = make_scene(workplane, LIGHT_METAL, center_mm=placement(part))
    truth = None if part["broken"] else truth_of(part, "spec")  # a broken part's jagged edge has no corner count
    run_scene(part["name"], photo, masks, truth, workplane, out, 0)
    table = json.loads((out / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    reference = cv2.imread(str(out / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0

    rows = search(out, table, reference, truth, render)
    baseline = out / ROUND / "baseline.py"
    baseline.write_text(baseline_code(table), encoding="utf-8")
    summary = validate(out, ROUND, [], baseline, reference, truth, None, table, checked_rows=rows, render=render,
                       design_intent=False)

    final, completion = None, None
    if summary["result_source"] in FOUND:
        final = Path(summary["result"]["file"])
        completion = suggest_completion(out, final, np.load(final.with_suffix(".default.mask.npy")), builder, client)
        if completion and completion["valid"]:
            final = out / "6_completion" / completion["program"]
    elif summary["result"]:
        final = Path(summary["result"]["file"])  # the measured shape (fallback)
    evaluation = None
    if final is not None:
        mask_path = final.with_suffix(".default.mask.npy")
        mask = np.load(mask_path) if mask_path.exists() else render(final, MM_PER_PIXEL)[0]
        evaluation = against_design(mask, part) if mask is not None else None

    usage = usage_ledger.summarize(out)
    report = {"seed": seed, "name": part["name"], "family": part["family"], "layout": part["layout"],
              "broken": part["broken"], "requested": len(rows), "passed": sum(1 for r in rows if "iou" in r and r["deviation_ok"]),
              "stopped_early": len(rows) < CANDIDATES, "result_source": summary["result_source"],
              "repair": None if not summary.get("repair") else {"passed": summary["repair"]["passed"],
                                                                 "rounds": len(summary["repair"]["rounds"])},
              "completion": None if not completion else {"valid": completion["valid"], "suggestion": completion["suggestion"]},
              "final": final.name if final else None, "evaluation": evaluation,
              "cost_usd": usage["known_cost_usd"], "seconds": round(time.perf_counter() - started, 1),
              "usage": usage["models"]}
    save_json(out / "report.json", report)
    return report


def percentile(values, q):
    return round(float(np.percentile(values, q)), 3) if values else None


def aggregate(reports):
    """The numbers asked for: success, topology, repair and completion rates, errors against the design, cost."""
    n = len(reports)
    found = [r for r in reports if r["result_source"] in FOUND]
    evaluated = [r for r in reports if r["evaluation"]]
    intact, broken = [r for r in evaluated if not r["broken"]], [r for r in evaluated if r["broken"]]
    repairs = [r for r in reports if r["repair"]]
    completions = [r for r in reports if r["completion"]]
    lengths = [abs(r["evaluation"]["length_error_pct"]) for r in evaluated]
    widths = [abs(r["evaluation"]["width_error_pct"]) for r in evaluated]
    holes = [r["evaluation"]["hole_diameter_error_mm"] for r in evaluated if r["evaluation"]["hole_diameter_error_mm"] is not None]
    costs = [r["cost_usd"] for r in reports]
    return {
        "parts": n,
        "design_found": len(found), "design_found_rate": round(len(found) / n, 3) if n else None,
        "found_by_repair": sum(1 for r in found if r["result_source"].startswith("repair")),
        "fallback": sum(1 for r in reports if (r["result_source"] or "").startswith("fallback")),
        "stopped_early": sum(1 for r in reports if r["stopped_early"]),
        "mean_candidates_requested": round(float(np.mean([r["requested"] for r in reports])), 2) if n else None,
        "topology_vs_design_intact": [sum(r["evaluation"]["topology_ok"] for r in intact), len(intact)],
        "topology_vs_design_broken_after_completion": [sum(r["evaluation"]["topology_ok"] for r in broken), len(broken)],
        "repair_triggered": len(repairs), "repair_passed": sum(1 for r in repairs if r["repair"]["passed"]),
        "completion_suggested": len(completions),
        "completion_valid": sum(1 for r in completions if r["completion"]["valid"]),
        "completion_on_broken": sum(1 for r in completions if r["broken"]),
        "completion_on_intact": sum(1 for r in completions if not r["broken"]),
        "broken_parts": sum(1 for r in reports if r["broken"]),
        "iou_vs_design": {"intact_median": percentile([r["evaluation"]["iou_vs_design"] for r in intact], 50),
                          "broken_median": percentile([r["evaluation"]["iou_vs_design"] for r in broken], 50)},
        "length_error_pct_abs": {"median": percentile(lengths, 50), "p90": percentile(lengths, 90), "max": max(lengths, default=None)},
        "width_error_pct_abs": {"median": percentile(widths, 50), "p90": percentile(widths, 90), "max": max(widths, default=None)},
        "hole_diameter_error_mm": {"median": percentile(holes, 50), "p90": percentile(holes, 90), "max": max(holes, default=None)},
        "cost_usd": {"total": round(sum(costs), 2), "per_part_mean": round(sum(costs) / n, 4) if n else None,
                     "per_part_p90": percentile(costs, 90)},
        "seconds_per_part_mean": round(float(np.mean([r["seconds"] for r in reports])), 1) if n else None,
    }


def main(arguments):
    count = int(next((a for a in arguments if a.isdigit()), 300))
    local = "--local" in arguments
    OUT.mkdir(parents=True, exist_ok=True)
    builder, client, reports, lock = Builder(), make_client(), [], threading.Lock()
    stop_reason = None

    def run_all(render):
        nonlocal stop_reason
        seeds = iter(range(count))
        with ThreadPoolExecutor(max_workers=PARTS_AT_ONCE) as pool:
            running = {}
            while True:
                while stop_reason is None and len(running) < PARTS_AT_ONCE:
                    seed = next(seeds, None)
                    if seed is None:
                        break
                    running[pool.submit(run_part, seed, render, builder, client)] = seed
                if not running:
                    break
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    seed = running.pop(future)
                    try:
                        report = future.result()
                    except Exception as error:  # one broken part must not stop the test
                        print(f"PART {seed} FAILED: {type(error).__name__}: {error}", flush=True)
                        continue
                    with lock:
                        reports.append(report)
                        spent = sum(r["cost_usd"] for r in reports)
                        print(f"PART {report['name']} {report['result_source']} cost ${report['cost_usd']:.3f} "
                              f"({len(reports)} done, ${spent:.2f} spent)", flush=True)
                        if spent >= BUDGET_USD:
                            stop_reason = f"budget reached: ${spent:.2f}"
                        elif len(reports) >= PROJECTION_AFTER and spent / len(reports) * count > BUDGET_USD:
                            stop_reason = f"projected ${spent / len(reports) * count:.2f} for {count} parts"
                        if len(reports) % REPORT_EVERY == 0:
                            interim = aggregate(reports)
                            save_json(OUT / f"interim_{len(reports)}.json", interim)
                            print("INTERIM " + json.dumps(interim), flush=True)

    try:
        if local:
            run_all(run_candidate)
        else:
            import modal_render

            with modal_render.app.run():
                run_all(modal_render.render)
    finally:
        builder.close()
    final = aggregate(reports) if reports else {}
    save_json(OUT / "report.json", {"stop_reason": stop_reason, "summary": final,
                                    "parts": sorted(reports, key=lambda r: r["seed"])})
    print(("STOPPED " + stop_reason) if stop_reason else "FINISHED", flush=True)
    print("FINAL " + json.dumps(final), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
