"""Compare candidate rounds from saved files (no API calls): compile rate, correct topology,
candidates within the deviation limits, output tokens and time.

Batch time is measured the same way for every round: from the earliest request's server
timestamp ("created") to the last response file being written. Newer rounds also store each
request's own wall time (elapsed_s).

Run: .venv\\Scripts\\python.exe compare_rounds.py
"""
import json
from pathlib import Path

import numpy as np

ROUNDS = [  # (part, scene folder, earlier round, new round)
    ("A", Path("outputs/e2e/A_light"), "candidates_intent", "candidates_kit"),
    ("B", Path("outputs/e2e/B"), "candidates_intent", "candidates_kit"),
    ("C", Path("outputs/e2e/C"), "candidates_intent", "candidates_kit"),
    ("D", Path("outputs/e2e/D"), "candidates_intent", "candidates_kit"),
    ("carton", Path("outputs/real/carton"), "candidates_clean", "candidates_kit"),
]


def round_stats(scene, folder):
    responses = sorted((scene / folder).glob("cand_*_response.json"))
    if not responses:
        return None
    data = [json.loads(p.read_text(encoding="utf-8")) for p in responses]
    answered = [d for d in data if "error" not in d]
    tokens = [(d.get("usage") or {}).get("completion_tokens") or 0 for d in answered]
    created = [d["created"] for d in answered if d.get("created")]
    batch = max(p.stat().st_mtime for p in responses) - min(created) if created else None
    summary_path = scene / f"5_summary_{folder}.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    elapsed = [d["elapsed_s"] for d in answered if "elapsed_s" in d]
    return {
        "candidates": len(data),
        "compiled": summary.get("compiled"),
        "correct_topology": summary.get("correct_topology") if summary.get("iou_ceiling") == summary.get("iou_ceiling")
        else None,  # NaN ceiling = real photo, no ground truth
        "within_deviation": summary.get("within_deviation"),
        "token_limit_hits": sum(1 for t in tokens if t >= 16000),
        "mean_tokens": round(float(np.mean(tokens))) if tokens else None,
        "batch_s": round(batch) if batch else None,
        "mean_request_s": round(float(np.mean(elapsed))) if elapsed else None,
        "winner_parameters": (summary.get("winner") or {}).get("parameter_count"),
        "winner_iou": (summary.get("winner") or {}).get("iou"),
    }


def main():
    rows = []
    for part, scene, earlier, new in ROUNDS:
        for label, folder in (("earlier", earlier), ("partkit", new)):
            stats = round_stats(scene, folder)
            if stats:
                rows.append({"part": part, "round": label, "folder": folder, **stats})
    header = (f"{'part':7s} {'round':8s} {'compiled':>8s} {'topology':>8s} {'in limits':>9s} {'16k hits':>8s} "
              f"{'tokens':>7s} {'batch s':>7s} {'req s':>6s} {'params':>6s} {'IoU':>7s}")
    print(header)
    for r in rows:
        def cell(key, width):
            value = r[key]
            return f"{'-' if value is None else value:>{width}}"
        print(f"{r['part']:7s} {r['round']:8s} {cell('compiled', 8)} {cell('correct_topology', 8)} "
              f"{cell('within_deviation', 9)} {cell('token_limit_hits', 8)} {cell('mean_tokens', 7)} "
              f"{cell('batch_s', 7)} {cell('mean_request_s', 6)} {cell('winner_parameters', 6)} {cell('winner_iou', 7)}")
    Path("outputs/round_comparison.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
