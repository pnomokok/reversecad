"""Test the Muse Wonder repair loop on cases where no candidate passes.

Cases: the cardboard (real photo; no candidate of its newest round returned code) and deliberately
broken candidates on the synthetic scenes A_light, C and D (a hole moved 4 mm, a corner cut 8 mm),
each shown alone. Reports per case: did the repair produce a passing program, in which round, does
Wonder's diagnosis name the injected fault, cost and time. Outputs in outputs/repair_tests/.

Run: .venv\\Scripts\\python.exe run_repair_tests.py [case ...]
"""
import json
import re
import sys
from pathlib import Path

import cv2

import usage_ledger
from e2e_pipeline import check_program, save_json
from parts.template_parts import part_truth
from repair import make_client, passed, repair_loop
from repair_inputs import write_broken_candidates
from webapp.replay import SCENE_PARTS

OUT = Path("outputs") / "repair_tests"
# What a diagnosis must mention to name the injected fault.
FAULT_WORDS = {"hole_shifted": r"hole.{0,80}(shift|moved|offset|position|misplac|displac|wrong place|off by)|"
                               r"(shift|moved|offset|misplac|displac).{0,80}hole",
               "corner_missing": r"corner|chamfer|cut off|cut-off|missing.{0,40}(edge|vertex)"}


def scene_cases():
    cases = {}
    for scene in ("A_light", "C", "D"):
        folder = Path("outputs") / "e2e" / scene
        table = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))["table"]
        for fault in ("hole_shifted", "corner_missing"):
            cases[f"{scene}_{fault}"] = {"folder": folder, "table": table, "fault": fault,
                                         "truth": part_truth(SCENE_PARTS[scene])}
    return cases


def cardboard_case():
    folder = Path("outputs") / "real" / "carton"
    table = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    return {"folder": folder, "table": table, "fault": None, "truth": None, "round": "candidates_arcs"}


def run_case(name, case, client):
    out = OUT / name
    out.mkdir(parents=True, exist_ok=True)
    (out / usage_ledger.FILE_NAME).unlink(missing_ok=True)  # each run of the test starts a fresh ledger
    reference_path = case["folder"] / "3_part_mask_topdown.png"
    reference = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE) > 0
    if case["fault"]:
        rows = []
        for fault, path in write_broken_candidates(out / "broken", case["table"]):
            if fault == case["fault"]:
                rows.append({"candidate": fault, **check_program(path, reference, case["truth"], case["table"])})
        assert not passed(rows[0]), f"{name}: the broken candidate passed the checks"
    else:  # the saved round as it is (its candidates returned no code)
        summary = json.loads((case["folder"] / f"5_summary_{case['round']}.json").read_text(encoding="utf-8"))
        rows = summary["candidates"]
    print(f"\n== {name}: {len(rows)} failed candidate(s) shown; asking Muse Wonder…", flush=True)
    result = repair_loop(out, case["table"], reference, reference_path, rows, truth=case["truth"], client=client)
    usage = usage_ledger.summarize(out)["models"].get(usage_ledger.WONDER, {})
    pattern = FAULT_WORDS.get(case["fault"])
    report = {
        "case": name, "fault": case["fault"], "passed": result["passed"],
        "rounds_used": len(result["rounds"]),
        "passing_round": next((r["round"] for r in result["rounds"] if r["passed"]), None),
        "diagnoses": [r["diagnosis"] for r in result["rounds"]],
        "diagnosis_names_fault": (bool(re.search(pattern, result["rounds"][0]["diagnosis"] or "", re.I | re.S))
                                  if pattern else None),
        "ious": [r["iou"] for r in result["rounds"]], "remaining_reasons": [r["reasons"] for r in result["rounds"]],
        "wonder_seconds": usage.get("seconds"), "wonder_input_tokens": usage.get("input_tokens"),
        "wonder_output_tokens": usage.get("output_tokens"), "wonder_reasoning_tokens": usage.get("reasoning_tokens"),
        "wonder_cost_usd": usage.get("cost_usd"),
    }
    save_json(out / "report.json", report)
    print(json.dumps(report, indent=2), flush=True)
    return report


def main(names):
    cases = {**scene_cases(), "carton": cardboard_case()}
    client = make_client()
    reports = [run_case(name, cases[name], client) for name in (names or cases)]
    save_json(OUT / "report.json", reports)
    print("\ncase                          passed  round  fault named  IoU     seconds  cost")
    for r in reports:
        print(f"{r['case']:28s}  {str(r['passed']):6s}  {str(r['passing_round']):5s}  {str(r['diagnosis_names_fault']):11s}"
              f"  {str(r['ious'][-1]):6s}  {r['wonder_seconds']!s:7s}  ${r['wonder_cost_usd'] or 0:.3f}")
    rate = sum(r["passed"] for r in reports) / len(reports)
    print(f"repair produced a passing program in {sum(r['passed'] for r in reports)}/{len(reports)} cases ({rate:.0%}); "
          f"total ${sum(r['wonder_cost_usd'] or 0 for r in reports):.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
