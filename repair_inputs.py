"""Inputs for the repair loop (Muse Wonder): deliberately broken candidates and the repair request.

broken_tables() makes wrong versions of a measurement table (a hole moved 4 mm, a corner cut off 8 mm); their
baseline programs are candidates with a known fault, to test whether a repair finds and fixes it.
build_repair_request() collects what Wonder is shown when no candidate passes: the model's view of
the measurements, the part's top-down mask, and for the best 2-3 failed candidates their code, their
XOR difference image and why they were rejected. It writes everything to a folder for inspection;
sending it is repair.py's job.
"""
import copy
import json
from pathlib import Path

import cv2
import numpy as np

from baseline_cad import baseline_code
from e2e_pipeline import xor_image
from model_view import model_view

HOLE_SHIFT_MM = 4.0
CORNER_CUT_MM = 8.0
MAX_FAILED_SHOWN = 3


def broken_tables(table):
    """{fault name: a copy of the table with that fault}; faults that the table cannot carry are left out."""
    faults = {}
    if table["holes"]:
        shifted = copy.deepcopy(table)
        u, v = shifted["holes"][0]["center_from_part_center_mm"]
        shifted["holes"][0]["center_from_part_center_mm"] = [round(u + HOLE_SHIFT_MM, 2), v]
        faults["hole_shifted"] = shifted
    if len(table["outline"]["polygon_mm"]) >= 4:
        missing = copy.deepcopy(table)
        polygon = [np.array(p, float) for p in missing["outline"]["polygon_mm"]]
        # Cut the corner farthest from the center CORNER_CUT_MM along both of its edges.
        far = max(range(len(polygon)), key=lambda i: polygon[i] @ polygon[i])
        corner, before, after = polygon[far], polygon[far - 1], polygon[(far + 1) % len(polygon)]
        cut = [corner + (neighbor - corner) * CORNER_CUT_MM / np.linalg.norm(neighbor - corner) for neighbor in (before, after)]
        polygon[far:far + 1] = cut
        missing["outline"]["polygon_mm"] = [[round(float(u), 2), round(float(v), 2)] for u, v in polygon]
        missing["outline"]["vertex_count"] += 1
        faults["corner_missing"] = missing
    return faults


def write_broken_candidates(folder, table, thickness=3.0):
    """Write one program per fault into `folder`; returns [(fault, path)]."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for fault, broken in broken_tables(table).items():
        path = folder / f"broken_{fault}.py"
        path.write_text(baseline_code(broken, thickness), encoding="utf-8")
        written.append((fault, path))
    return written


def failure_reasons(row):
    """Why a checked candidate failed, as short lines (rejection details or the build error)."""
    if "error" in row:
        return [row["error"].strip().splitlines()[-1]]
    reasons = list(row.get("topology_issues") or [])
    reasons += [f"{d['dimension']}: measured {d['measured_mm']}, candidate {d['candidate_mm']}, "
                f"off by {d['deviation_mm']} mm (limit {d['limit_mm']})" for d in row.get("deviation", []) if not d["ok"]]
    return reasons


def pick_failed(rows, count=MAX_FAILED_SHOWN):
    """The most useful failed candidates to show: ones that built (best IoU first), then build failures with code."""
    built = sorted((r for r in rows if "iou" in r and failure_reasons(r)), key=lambda r: -r["iou"])
    crashed = [r for r in rows if "error" in r and Path(r["file"]).exists()]
    return (built + crashed)[:count]


def build_repair_request(folder, table, mask_path, failed_rows):
    """Write the repair request to `folder` (request.json, mask.png, xor_<n>.png) and return it.

    failed_rows are rows from check_program (with their private _alignment for the XOR image).
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    cv2.imwrite(str(folder / "mask.png"), mask)
    candidates = []
    for n, row in enumerate(failed_rows, 1):
        entry = {"name": Path(row["file"]).name, "code": Path(row["file"]).read_text(encoding="utf-8"),
                 "reasons": failure_reasons(row), "iou": row.get("iou"), "xor_image": None}
        if "_alignment" in row:
            cv2.imwrite(str(folder / f"xor_{n}.png"), xor_image(row["_alignment"]))
            entry["xor_image"] = f"xor_{n}.png"
        candidates.append(entry)
    request = {"measurements": model_view(table), "mask_image": "mask.png", "candidates": candidates}
    (folder / "request.json").write_text(json.dumps(request, indent=2, default=lambda o: o.item()), encoding="utf-8")
    return request


def crop_to_content(image, margin=10):
    """Crop an image (mask or XOR) to its non-black content, so small images keep the detail."""
    gray = image if image.ndim == 2 else image.max(axis=2)
    ys, xs = np.nonzero(gray)
    if not len(ys):
        return image
    return image[max(ys.min() - margin, 0):ys.max() + margin, max(xs.min() - margin, 0):xs.max() + margin]
