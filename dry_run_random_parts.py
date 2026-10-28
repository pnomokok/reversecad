"""Check the random part generator without any model: build, render and measure every part.

For each seed: is the part a valid solid, does its measured table have the right topology against its
own spec, and do the break cues flag the broken parts and only those. Report in
outputs/random_parts/dry_run.json.

Run: .venv\\Scripts\\python.exe dry_run_random_parts.py [count]
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from break_cues import find_break_cues
from part_measurements import check_topology, measure_part
from parts.random_parts import make_random_part, random_part, truth_of
from render_silhouette import render_top_silhouette

SCALE = np.diag([0.1, 0.1, 1.0])
OUT = Path("outputs") / "random_parts"


def check(seed):
    part = random_part(seed)
    row = {"seed": seed, "family": part["family"], "layout": part["layout"], "broken": part["broken"],
           "holes": len(part["spec"]["holes"])}
    try:
        solid = make_random_part(part).rotate((0, 0, 0), (0, 0, 1), 8)
        table = measure_part(render_top_silhouette(solid, 0.1) > 0, SCALE)
    except Exception as error:  # an invalid part: count it, keep going
        return {**row, "error": f"{type(error).__name__}: {error}"}
    ok, issues = check_topology(table, truth_of(part, "spec"))
    cues = find_break_cues(table)
    return {**row, "topology_ok": ok, "issues": issues, "cues": sorted(c["kind"] for c in cues["cues"]),
            "flagged": cues["break_likely"]}


def main(count):
    started = time.perf_counter()
    rows = [check(seed) for seed in range(count)]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dry_run.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    valid = [r for r in rows if "error" not in r]
    broken = [r for r in valid if r["broken"]]
    intact = [r for r in valid if not r["broken"]]
    print(f"{count} parts in {time.perf_counter() - started:.0f} s; families {dict(Counter(r['family'] for r in rows))}; "
          f"broken {dict(Counter(r['broken'] for r in rows if r['broken']))}")
    print(f"valid solids {len(valid)}/{count}; measured topology matches the spec {sum(r['topology_ok'] for r in valid)}/{len(valid)}")
    print(f"break cues: broken parts flagged {sum(r['flagged'] for r in broken)}/{len(broken)}, "
          f"intact parts flagged {sum(r['flagged'] for r in intact)}/{len(intact)}")
    for r in [r for r in valid if not r["topology_ok"]][:5] + [r for r in rows if "error" in r][:5]:
        print("  ", r)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 300)
