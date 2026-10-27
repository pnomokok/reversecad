"""Screen and execute one candidate program safely; return its silhouette or the error.

Order: static check (check_code) -> separate process with a timeout
(candidate_runner.py) -> load the saved mask. Optional overrides change
build_part's keyword arguments, for testing what a parameter really controls.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from candidates import check_code

ROOT = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 120


def run_candidate(code_path, mm_per_pixel, overrides=None, tag="default"):
    """Return (mask or None, error message or None)."""
    code_path = Path(code_path)
    problems = check_code(code_path.read_text(encoding="utf-8"))
    if problems:
        return None, "rejected before running: " + "; ".join(problems)

    mask_path = code_path.with_suffix(f".{tag}.mask.npy")
    command = [sys.executable, str(ROOT / "candidate_runner.py"), str(code_path), str(mask_path), str(mm_per_pixel),
               json.dumps(overrides or {})]
    try:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {TIMEOUT_SECONDS} s"
    if completed.returncode != 0:
        lines = [line for line in completed.stderr.strip().splitlines() if "ezdxf" not in line]
        return None, "\n".join(lines[-6:])  # the end of the traceback holds the actual error
    return np.load(mask_path), None
