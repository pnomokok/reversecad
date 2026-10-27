"""Read a saved pipeline run (outputs/e2e/<scene>/) and shape it for the web screens.

Replay mode: everything comes from files a run already wrote, plus SAM's cached
answers; no API is called (a missing cache file is an error, not a new request).
The measurement functions are only reused, never changed.
"""
import ast
import functools
import json
from pathlib import Path

import cv2
import numpy as np

from design_intent import parameters
from e2e_pipeline import CARD_PROMPTS, card_aspect_ok, pixel_to_mm_scales
from homography import card_corners, largest_contour, to_mm
from part_measurements import classify_hole
from sam_client import load_photo, parse_detections

RUNS_DIR = Path("outputs") / "e2e"


def list_runs():
    """Saved runs that reached the measurement step."""
    return sorted(p.name for p in RUNS_DIR.iterdir() if (p / "3_measurements.json").exists()) \
        if RUNS_DIR.exists() else []


def run_dir(name, measured=True):
    """A run's folder; measured=False also accepts a live upload that has not been measured yet."""
    path = (RUNS_DIR / name).resolve()
    required = "3_measurements.json" if measured else "1_scene.png"
    if path.parent != RUNS_DIR.resolve() or not (path / required).exists():
        raise FileNotFoundError(f"no saved run named {name!r}")
    return path


def photo_path(name):
    return run_dir(name, measured=False) / "1_scene.png"


def _cached_card_mask(folder, image):
    """The card mask the run used: the first card prompt whose cached answer has a card-shaped mask.

    Decoding SAM's mask text is slow (pure Python, about 15 s for a card), so the decoded mask is
    saved once as 3_mask_card.png (newer pipeline runs write it themselves) and read from there.
    """
    saved = folder / "3_mask_card.png"
    if saved.exists():
        return cv2.imread(str(saved), cv2.IMREAD_GRAYSCALE) > 0
    for prompt in CARD_PROMPTS:
        cache = folder / "sam" / f"{prompt.replace(' ', '_')}.txt"
        if not cache.exists():
            continue
        found = [d for d in parse_detections(cache.read_text(encoding="utf-8"), image.size) if card_aspect_ok(d.mask)]
        if found:
            mask = max(found, key=lambda d: d.confidence or 0).mask
            cv2.imwrite(str(saved), mask.astype(np.uint8) * 255)
            return mask
    raise FileNotFoundError("no cached card mask for this run (replay never calls SAM)")


# newest first; medium reasoning effort is the default since the effort comparison
CANDIDATE_ROUNDS = ["candidates_arcs_effort_medium", "candidates_arcs", "candidates_kit", "candidates_intent"]


def candidate_round(name):
    """The newest saved candidate round of a run (its folder name)."""
    folder = run_dir(name)
    for round_name in CANDIDATE_ROUNDS:
        if (folder / f"5_summary_{round_name}.json").exists():
            return round_name
    raise FileNotFoundError(f"no saved candidate round for {name!r}")


def _status(row):
    """(status, reasons) for one candidate row of a saved summary."""
    if "error" in row:
        return "failed", [row["error"].strip().splitlines()[-1]]
    reasons = []
    if row.get("topology_ok") is False:
        reasons += row.get("topology_issues", [])
    if not row.get("deviation_ok", True):
        reasons += [f"{d['dimension']}: off by {d['deviation_mm']} mm (limit {d['limit_mm']})"
                    for d in row.get("deviation", []) if not d["ok"]]
    return ("rejected" if reasons else "passed"), reasons


def candidate_event(name, row):
    """One candidate row (as saved in a summary) as a screen-3 event; live mode sends the same."""
    status, reasons = _status(row)
    return {"type": "candidate", "candidate": row["candidate"], "status": status, "reasons": reasons,
            "iou": row.get("iou"), "parameters": row.get("parameter_count"),
            "silhouette": f"/api/runs/{name}/candidates/{row['candidate']}/silhouette.png"
            if status != "failed" else None}


def done_event(summary, round_name):
    """The end of a candidate round: the winner (or the fallback) and counts."""
    winner = (summary.get("winner") or {}).get("candidate")
    return {"type": "done", "round": round_name, "winner": winner,
            "result_source": summary.get("result_source", "candidate" if winner else None),
            "compiled": summary["compiled"], "candidate_count": summary["candidate_count"]}


def candidate_events(name):
    """The saved candidate round as a list of events, in the order they would arrive live."""
    round_name = candidate_round(name)
    summary = json.loads((run_dir(name) / f"5_summary_{round_name}.json").read_text(encoding="utf-8"))
    return [candidate_event(name, row) for row in summary["candidates"]] + [done_event(summary, round_name)]


def silhouette_png(name, candidate):
    """A candidate's saved top-view silhouette (from its render), cropped, as PNG bytes.

    Found by file, not by summary, so live runs can show it before their round is finished.
    """
    folder = run_dir(name)
    paths = [folder / round_name / f"cand_{int(candidate)}.default.mask.npy" for round_name in CANDIDATE_ROUNDS]
    path = next((p for p in paths if p.exists()), None)
    if path is None:
        raise FileNotFoundError(f"no saved silhouette for candidate {candidate}")
    mask = np.load(path)
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ok, data = cv2.imencode(".png", np.pad(crop, 20).astype(np.uint8) * 255)
    return data.tobytes()


def result_program(name):
    """(program path, source label) of the run's result: the winner, or the baseline fallback."""
    summary = json.loads((run_dir(name) / f"5_summary_{candidate_round(name)}.json").read_text(encoding="utf-8"))
    result = summary.get("result") or summary.get("winner")
    if not result:
        raise FileNotFoundError("this run has no result program")
    path = Path(result["file"].replace("\\", "/"))
    source = summary.get("result_source", "candidate")
    return path, source


def winner(name):
    """Screen 4: the result program's named parameters with their defaults (read from the code, not run)."""
    path, source = result_program(name)
    params = [{"name": p, "default": v} for p, v in parameters(path.read_text(encoding="utf-8"))
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return {"name": name, "program": path.name, "source": source, "parameters": params}


def program_with_defaults(name, values):
    """The result program's source with build_part's defaults replaced by `values` (name -> number).

    Only the default values change (located by the parser, replaced from the end of the text so
    earlier positions stay valid); the rest of the code is kept as written.
    """
    path, _ = result_program(name)
    source = path.read_text(encoding="utf-8")
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "build_part")
    args = function.args
    pairs = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
    pairs += [(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None]
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for arg, default in pairs:
        if arg.arg in values:
            start = offsets[default.lineno - 1] + default.col_offset
            end = offsets[default.end_lineno - 1] + default.end_col_offset
            edits.append((start, end, repr(round(float(values[arg.arg]), 4))))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def _pixels(points):
    return [[round(float(x), 1), round(float(y), 1)] for x, y in points]


def info(name):
    """Light data for screen 1: the saved click and the photo size (no mask decoding)."""
    folder = run_dir(name)
    attempts = json.loads((folder / "2_sam_attempts.json").read_text(encoding="utf-8"))
    height, width = cv2.imread(str(folder / "1_scene.png"), cv2.IMREAD_GRAYSCALE).shape
    return {"name": name, "click_px": attempts.get("click"), "image_size": [width, height]}


@functools.lru_cache(maxsize=16)
def analysis(name):
    """Data for screens 1-2: photo size, click, card corners, part outline and holes (pixels), table (mm)."""
    folder = run_dir(name)
    measurements = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))
    attempts = json.loads((folder / "2_sam_attempts.json").read_text(encoding="utf-8"))
    image = load_photo(folder / "1_scene.png")
    card_mask = _cached_card_mask(folder, image)
    scales, scale_used, differences = pixel_to_mm_scales(card_mask)
    pixel_to_mm = scales[scale_used]

    method = measurements["chosen_method"]
    part_mask = cv2.imread(str(folder / f"3_mask_{method}.png"), cv2.IMREAD_GRAYSCALE) > 0
    contours, hierarchy = cv2.findContours(part_mask.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    parents = hierarchy[0][:, 3]
    outer = max((i for i in range(len(contours)) if parents[i] == -1), key=lambda i: cv2.contourArea(contours[i]))
    holes = []
    for i, contour in enumerate(contours):
        if parents[i] != outer or cv2.contourArea(contour) < 20:
            continue
        points = contour.reshape(-1, 2).astype(float)
        shape, info = classify_hole(to_mm(points, pixel_to_mm).astype(np.float32))
        size = (f"Ø{2 * np.sqrt(info['area'] / np.pi):.2f}" if shape == "circle"
                else f"{info['length']:.2f} × {info['width']:.2f}")
        holes.append({"shape": shape, "label": f"{shape} {size} mm", "contour_px": _pixels(points),
                      "center_px": _pixels([points.mean(axis=0)])[0]})

    table = measurements["table"]
    return {
        "name": name,
        "image_size": list(image.size),
        "click_px": attempts.get("click"),
        "part_found_by": attempts.get("chosen_source"),
        "card_corners_px": _pixels(card_corners(largest_contour(card_mask))),
        "card_edge_differences_pct": [round(float(d) * 100, 2) for d in differences],
        "scale_used": scale_used,
        "hole_method": method,
        "outline_px": _pixels(contours[outer].reshape(-1, 2)),
        "outline_mm": {"length": table["outline"]["length_mm"], "width": table["outline"]["width_mm"],
                       "corners": table["outline"]["vertex_count"]},
        "holes": holes,
        "table": {"outline": {k: table["outline"][k] for k in ("length_mm", "width_mm", "vertex_count")},
                  "hole_count": table["hole_count"],
                  "holes": [{k: v for k, v in h.items() if k not in ("polygon_mm",)} for h in table["holes"]]},
    }
