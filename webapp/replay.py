"""Read a saved pipeline run (outputs/e2e/<scene>/) and shape it for the web screens.

Replay mode: everything comes from files a run already wrote, plus SAM's cached
answers; no API is called (a missing cache file is an error, not a new request).
The measurement functions are only reused, never changed.
"""
import ast
import contextvars
import functools
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from break_cues import ROUGH_RMS_MM, find_break_cues
from completion import topdown_photo, verified_stored_parts
from repair import REPAIR_NUMBER
from repair_inputs import MAX_FAILED_SHOWN, failure_reasons
from resolution import card_long_edge_px, resolution_warning
from tilt_warning import card_tilt, tilt_warning
from design_intent import parameters, replace_defaults
from deviation_check import describe
from e2e_pipeline import CARD_PROMPTS, MM_PER_PIXEL, card_aspect_ok, pixel_to_mm_scales
from homography import card_corners, largest_contour, to_mm
from iou import _centroid_and_angle, aligned_iou
from part_measurements import classify_hole
from sam_client import load_photo, parse_detections

RUNS_DIR = Path("outputs") / "e2e"  # runs made on this machine (git-ignored), live runs too
SAMPLES_DIR = Path("samples")  # small sample runs kept in the repository (make_sample.py)
SOURCES = [RUNS_DIR, SAMPLES_DIR]  # a run name is looked up in this order


def _photo(folder):
    """The run's photo: 1_scene.png (pipeline runs) or 1_scene.jpg (compact sample runs)."""
    return next((folder / f"1_scene{ext}" for ext in (".png", ".jpg") if (folder / f"1_scene{ext}").exists()), None)


def list_runs():
    """Saved runs that reached the measurement step."""
    names = {p.name for source in SOURCES if source.exists()
             for p in source.iterdir() if (p / "3_measurements.json").exists()}
    return sorted(names)


def list_samples():
    """Sample names (samples/ only), so clients can tell recorded samples from local runs."""
    return sorted(p.name for p in SAMPLES_DIR.iterdir() if p.is_dir()) if SAMPLES_DIR.exists() else []


def run_dir(name, measured=True):
    """A run's folder; measured=False also accepts a live upload that has not been measured yet."""
    for source in SOURCES:
        path = (source / name).resolve()
        if path.parent != source.resolve():
            continue  # the name tried to leave the folder
        if (path / "3_measurements.json").exists() if measured else _photo(path):
            return path
    raise FileNotFoundError(f"no saved run named {name!r}")


def photo_path(name):
    return _photo(run_dir(name, measured=False))


def reference_path(name):
    """The run's reference top-view mask (3_part_mask_topdown.png) every candidate is checked against."""
    path = run_dir(name, measured=False) / "3_part_mask_topdown.png"
    if not path.exists():
        raise FileNotFoundError(f"run {name!r} has no reference mask")
    return path


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
SILHOUETTE_BGRA = (225, 226, 229, 255)  # the design's light surface color (--color-text in tokens.css)


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
        reasons += [describe(d)
                    for d in row.get("deviation", []) if not d["ok"]]
    return ("rejected" if reasons else "passed"), reasons


def plain_reason(reason):
    """A rejection or failure reason in plain words (the technical text stays available alongside)."""
    text = reason.lower()
    if text.startswith("no python code block"):
        return ("ran out of reasoning budget, no code returned" if "finish=length" in text
                else "the answer contained no code")
    if text.startswith("request failed"):
        return "the request to the model failed"
    if text.startswith("rejected before running"):
        return "the code used something that is not allowed"
    if text.startswith("emptypart"):
        return "the program built an empty part"
    if "timed out" in text:
        return "the program took too long to build"
    if ": off by" in text:
        dimension, rest = reason.split(": off by", 1)
        return f"{dimension} is off by{rest}"
    if any(word in text for word in ("error", "exception")) or ":" in reason.split(" ")[0]:
        return "the program crashed while building the part"
    return reason


def fit_to_measurements_mm(row):
    """Largest distance (mm) from a measured outline point (corner, or a point on an arc) to the
    candidate's outline, from the deviation check; None if the candidate was not checked.

    This is how well the candidate follows the measurements, not how accurate it is: the
    measurements themselves carry the photo's error (see ground_truth_error)."""
    distances = [abs(d["deviation_mm"]) for d in row.get("deviation", [])
                 if d["dimension"].startswith(("corner", "arc")) and isinstance(d.get("deviation_mm"), (int, float))]
    return round(max(distances), 2) if distances else None


# Synthetic scenes (run_template_scenes.py) and the template part each one shows: their true
# dimensions are known. A real-photo run has ruler truth when it ships 1_truth.json.
SCENE_PARTS = {"A_light": "A", "A_light_repair": "A", "A_dark": "A", "B": "B", "C": "C", "D": "D", "E": "E"}


def _ruler_truth(name):
    """Ruler-measured truth (length, width, hole diameters) a real-photo run ships; else None."""
    try:
        path = run_dir(name) / "1_truth.json"
    except FileNotFoundError:
        return None  # no such run, so no truth
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def ground_truth_error(name, row):
    """The candidate's outline and hole sizes against the true part; else None.

    {"length": [model, true], "width": [model, true], "holes": [[model, true], ...] or None if the
    hole counts differ}. Sizes in mm; holes as equal-area diameters, matched by size.
    scenes compare against the CAD design ("kind": "cad"), real-photo runs with 1_truth.json against the ruler ("kind": "ruler").
    """
    if not row.get("outline_mm"):
        return None
    if name in SCENE_PARTS:
        from parts.template_parts import part_truth  # loads CadQuery; only needed for synthetic scenes
        truth, kind = part_truth(SCENE_PARTS[name]), "cad"
    else:
        truth, kind = _ruler_truth(name), "ruler"
        if truth is None:
            return None
    true_holes = sorted(h["diameter_mm"] for h in truth["holes"])
    model_holes = sorted(row.get("hole_diameters_mm") or [])
    return {"kind": kind, "length": [row["outline_mm"][0], truth["length"]], "width": [row["outline_mm"][1], truth["width"]],
            "holes": [[m, round(t, 2)] for m, t in zip(model_holes, true_holes)]
            if len(model_holes) == len(true_holes) else None}


def candidate_event(name, row, round_name=None):
    """One candidate row (as saved in a summary) as a screen-3 event; live mode sends the same."""
    status, reasons = _status(row)
    query = f"?round={round_name}" if round_name else ""
    return {"type": "candidate", "candidate": row["candidate"], "status": status, "reasons": reasons,
            "plain_reasons": [plain_reason(r) for r in reasons],
            "iou": row.get("iou"), "parameters": row.get("parameter_count"),
            "fit_mm": fit_to_measurements_mm(row), "ground_truth": ground_truth_error(name, row),
            "outline_mm": row.get("outline_mm"), "hole_count": row.get("hole_count"),
            "label": row.get("label"), "diagnosis": row.get("diagnosis"),  # set for a repaired program
            "style": row.get("style"),  # the approach the candidate was asked with (candidates.STYLES)
            "silhouette": f"/api/runs/{name}/candidates/{row['candidate']}/silhouette.png{query}"
            if status != "failed" else None}


def irregularities(name):
    """What the break cues found, for the "no design found" panel: rough edges (share of the outline and the
    worst roughness), material missing against the mirror image, gaps in hole patterns, holes found."""
    table = json.loads((run_dir(name) / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    cues = find_break_cues(table)["cues"]
    contour = np.array(table["outline"].get("contour_mm") or [], float)
    perimeter = float(np.linalg.norm(np.diff(np.vstack([contour, contour[:1]]), axis=0), axis=1).sum()) if len(contour) else 0
    rough = [c for c in cues if c["kind"] == "rough_edge"]
    missing = [c for c in cues if c["kind"] == "missing_material"]
    gaps = [c for c in cues if c["kind"] in ("missing_hole", "partial_hole")]
    return {"rough_edges": len(rough), "rough_length_mm": round(sum(c["length_mm"] for c in rough), 1),
            "perimeter_mm": round(perimeter, 1),
            "rough_share": round(sum(c["length_mm"] for c in rough) / perimeter, 3) if perimeter else None,
            "worst_roughness_mm": max((c["roughness_mm"] for c in rough), default=None),
            "roughness_limit_mm": ROUGH_RMS_MM,
            "missing_material_mm2": round(sum(c["area_mm2"] for c in missing), 1), "pattern_gaps": len(gaps),
            "holes": table["hole_count"]}


def result_note(name, summary):
    """Why the result is the measured shape, in plain words, when no program passed; else None."""
    if not (summary.get("result_source") or "").startswith("fallback"):
        return None
    table = json.loads((run_dir(name) / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    if any(cue["kind"] == "rough_edge" for cue in find_break_cues(table)["cues"]):
        return "The edges are irregular; the measured shape is shown."
    return "No candidate passed every check; the measured shape is shown."


def round_label(name, round_name):
    """The round in plain words ("Round 1 · medium effort"): its place among the run's saved rounds, oldest
    first, and the reasoning effort the folder name records (none when the round predates the setting)."""
    try:
        folder = run_dir(name)
    except FileNotFoundError:
        return None
    saved = [r for r in reversed(CANDIDATE_ROUNDS) if (folder / f"5_summary_{r}.json").exists()]
    number = saved.index(round_name) + 1 if round_name in saved else len(saved) + 1
    effort = round_name.rsplit("_effort_", 1)[1] if "_effort_" in round_name else None
    return f"Round {number}" + (f" · {effort} effort" if effort else "")


def repair_inputs_count(name, round_name, rows):
    """How many failed candidates Muse Wonder was given in repair round 1, by the same rule as
    repair_inputs.pick_failed: failures that built (best IoU first), then build failures that left code,
    at most MAX_FAILED_SHOWN. Returns (given, failed in total)."""
    built = [r for r in rows if "iou" in r and failure_reasons(r)]
    crashed = [r for r in rows if "error" in r and _program_path(name, round_name, r["file"]).exists()]
    failed = [r for r in rows if "error" in r or ("iou" in r and failure_reasons(r))]
    return min(MAX_FAILED_SHOWN, len(built) + len(crashed)), len(failed)


def done_event(summary, round_name, note=None, name=None):
    """The end of a candidate round: the winner (or the fallback), counts, and why if it fell back."""
    winner = (summary.get("winner") or {}).get("candidate")
    fallback = None
    baseline = summary.get("baseline") or {}
    if (summary.get("result_source") or "").startswith("fallback") and "iou" in baseline:
        fallback = {"iou": baseline["iou"], "fit_mm": fit_to_measurements_mm(baseline),
                    "outline_mm": baseline.get("outline_mm"), "parameters": baseline.get("parameter_count"),
                    "silhouette": f"/api/runs/{name}/candidates/0/silhouette.png?round={round_name}" if name else None}
    return {"type": "done", "round": round_name, "round_label": round_label(name, round_name) if name else None,
            "winner": winner, "note": note, "fallback": fallback,
            "result_source": summary.get("result_source", "candidate" if winner else None),
            "compiled": summary["compiled"], "candidate_count": summary["candidate_count"],
            "durations": summary.get("durations"),  # measured stage seconds; runs before them have none
            "usage": summary.get("usage")}  # model calls, tokens and cost; runs before the ledger have none


def candidate_events(name, round_name=None):
    """A saved candidate round (default: the newest) as a list of events, in the order they would arrive live."""
    if round_name is None:
        round_name = candidate_round(name)
    elif round_name not in CANDIDATE_ROUNDS or not (run_dir(name) / f"5_summary_{round_name}.json").exists():
        raise FileNotFoundError(f"no saved round {round_name!r} for {name!r}")
    summary = json.loads((run_dir(name) / f"5_summary_{round_name}.json").read_text(encoding="utf-8"))
    events = [candidate_event(name, row, round_name) for row in summary["candidates"]]
    repaired = summary.get("repair") or {}
    events += [e for entry in repaired.get("rounds", []) for e in ({"type": "repair_started", "round": entry.get("round"), "seconds": entry.get("seconds")}, {"type": "repair", **entry})]
    if repaired.get("passed"):
        event = candidate_event(name, repaired["result"])
        if (repaired.get("rounds") or [{}])[-1].get("round") == 1:  # round 1 saw only the candidates
            event["repair_given"], event["failed_count"] = repair_inputs_count(name, round_name, summary["candidates"])
        events.append(event)
    return events + [done_event(summary, round_name, result_note(name, summary), name)]


def _program_path(name, round_name, file):
    """A summary's program path inside this run: a candidate round's folder or a repair round's folder."""
    path = Path(file.replace("\\", "/"))
    folder = path.parent.name if path.parent.name.startswith("repair_round_") else round_name
    return run_dir(name) / folder / path.name


def silhouette_png(name, candidate, round_name=None):
    """A candidate's saved top-view silhouette (from its render), cropped, as PNG bytes.

    Found by file, not by summary, so live runs can show it before their round is finished.
    With round_name, only that round's folder is searched.
    """
    folder = run_dir(name)
    if round_name is not None and round_name not in CANDIDATE_ROUNDS:
        raise FileNotFoundError(f"unknown round {round_name!r}")
    if int(candidate) == 0:  # the baseline (the measured shape), shown when no candidate passed
        paths = [folder / r / f"baseline.default.mask{ext}" for r in ([round_name] if round_name else CANDIDATE_ROUNDS)
                 for ext in (".npy", ".png")]
    elif int(candidate) > REPAIR_NUMBER:  # a repaired program (repair.py numbers them 101, 102)
        repair = folder / f"repair_round_{int(candidate) - REPAIR_NUMBER}"
        paths = [repair / "repaired.default.mask.npy", repair / "repaired.default.mask.png"]
    else:
        paths = [folder / r / f"cand_{int(candidate)}.default.mask{ext}"
                 for r in ([round_name] if round_name else CANDIDATE_ROUNDS) for ext in (".npy", ".png")]  # .png in compact samples
    path = next((p for p in paths if p.exists()), None)
    if path is None:
        raise FileNotFoundError(f"no saved silhouette for candidate {candidate}")
    mask = np.load(path) if path.suffix == ".npy" else cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) > 0
    ys, xs = np.nonzero(mask)
    crop = np.pad(mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1], 20)
    # Light shape on a transparent background, so it sits on the card's own dark surface.
    image = np.zeros((*crop.shape, 4), dtype=np.uint8)
    image[crop] = SILHOUETTE_BGRA
    ok, data = cv2.imencode(".png", image)
    return data.tobytes()


COMPLETION_SOURCE = "completion suggested by Muse Wonder"
FALLBACK_SOURCE = "fallback: measured shape, no design intent"


# Completion decisions for runs under samples/ (and so every run of the online demo) are kept by each
# browser, never written to disk: the browser sends its answer with every request (X-Completion-Decision,
# read by the server into this variable), so one visitor's Apply or Ignore never reaches another and
# samples/ stays as committed. Runs of your own photos keep their answer in 6_completion/decision.json.
client_decision = contextvars.ContextVar("client_decision", default=None)
BROWSER_APPLIED_DIR = Path("outputs") / "web" / "applied"  # completed programs for browser-kept answers


def decisions_in_browser(name):
    """True when the run's completion answer is kept by the browser (a run under samples/)."""
    return is_sample(name)


def _checked_answer(data, decision, values):
    """The answer {"decision", "values"} after the same checks for both kinds of storage; else ValueError."""
    if decision not in (None, "apply", "ignore"):
        raise ValueError("decision must be apply or ignore")
    if decision == "apply" and not data.get("valid"):
        raise ValueError("this suggestion did not pass its check")
    asked = {part["name"] for part in data.get("parts") or [] if part["basis"] in ("estimated", "optional")}
    values = values or {}
    if not isinstance(values, dict):
        raise ValueError("values must be an object")
    for key, value in values.items():
        if key not in asked or not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"not an answer to this suggestion's questions: {key}")
    return {"decision": decision, "values": values}


def _browser_answer(data):
    """The browser's answer for this request, checked; a stale or broken one counts as no answer."""
    answer = client_decision.get()
    if not isinstance(answer, dict):
        return {}
    try:
        return _checked_answer(data, answer.get("decision"), answer.get("values"))
    except ValueError:
        return {}


def completion(name):
    """The run's completion suggestion (6_completion/completion.json) with the user's decision, or None.

    "stored" says where the decision lives: "browser" (samples) or "server" (decision.json).
    """
    folder = run_dir(name) / "6_completion"
    path = folder / "completion.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    data["parts"] = verified_stored_parts(folder.parent, data)
    if decisions_in_browser(name):
        answer, data["stored"] = _browser_answer(data), "browser"
    else:
        decision = folder / "decision.json"
        answer = json.loads(decision.read_text(encoding="utf-8")) if decision.exists() else {}
        data["stored"] = "server"
    data["decision"], data["answers"] = answer.get("decision"), answer.get("values") or {}
    data["added_stl"] = f"/api/runs/{name}/completion/added.stl" if (folder / "added.stl").exists() else None
    data["added_volume_mm3"] = (data.get("check") or {}).get("added_volume_mm3")
    return data


def decide_completion(name, decision, values=None):
    """Check and store the user's answer to the suggestion: "apply", "ignore", or None to undo it.

    values: the user's answers to the estimated and optional parts (parameter -> number; 0 leaves an
    optional feature out). Applying writes applied.py, the completed program with those as defaults.
    For a run whose answer the browser keeps (samples/), nothing is written: the checked answer is
    returned for the browser to store and send back.
    """
    data = completion(name)
    if data is None:
        raise FileNotFoundError("this run has no completion suggestion")
    answer = _checked_answer(data, decision, values)
    if decisions_in_browser(name):
        return answer
    folder = run_dir(name) / "6_completion"
    path = folder / "decision.json"
    (folder / "applied.py").unlink(missing_ok=True)
    if decision is None:
        path.unlink(missing_ok=True)
        return answer
    if decision == "apply":
        source = (folder / data["program"]).read_text(encoding="utf-8")
        (folder / "applied.py").write_text(replace_defaults(source, answer["values"]), encoding="utf-8")
    path.write_text(json.dumps(answer), encoding="utf-8")
    return answer


def _browser_applied_program(name, data):
    """The completed program with the browser's answers as defaults, in a git-ignored cache folder
    (named by a hash of what it is made from, so equal answers share one file)."""
    source = (run_dir(name) / "6_completion" / data["program"]).read_text(encoding="utf-8")
    text = replace_defaults(source, data["answers"])
    key = hashlib.sha256(json.dumps([name, text]).encode("utf-8")).hexdigest()[:24]
    path = BROWSER_APPLIED_DIR / key / "applied.py"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return path


def result_program(name):
    """(program path, source label) of the run's result: the applied completion, else the winner, or the
    baseline fallback."""
    applied = completion(name)
    if applied and applied["decision"] == "apply" and applied.get("valid"):
        if applied["stored"] == "browser":
            return _browser_applied_program(name, applied), COMPLETION_SOURCE
        folder = run_dir(name) / "6_completion"
        program = folder / "applied.py" if (folder / "applied.py").exists() else folder / applied["program"]
        return program, COMPLETION_SOURCE
    round_name = candidate_round(name)
    summary = json.loads((run_dir(name) / f"5_summary_{round_name}.json").read_text(encoding="utf-8"))
    result = summary.get("result") or summary.get("winner")
    if not result:
        raise FileNotFoundError("this run has no result program")
    # By file name inside the run's own folders, so a run still works after it is moved (samples).
    path = _program_path(name, round_name, result["file"])
    source = summary.get("result_source", "candidate")
    return path, source


def _result_row(name):
    """The summary row of the result program (winner or baseline), or None."""
    round_name = candidate_round(name)
    summary = json.loads((run_dir(name) / f"5_summary_{round_name}.json").read_text(encoding="utf-8"))
    return summary.get("result") or summary.get("winner")


def winner(name):
    """Screen 4: the result program's named parameters with their defaults (read from the code, not run),
    and its scores against the photo."""
    path, source = result_program(name)
    params = [{"name": p, "default": v} for p, v in parameters(path.read_text(encoding="utf-8"))
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
    row = _result_row(name) or {}
    summary = json.loads((run_dir(name) / f"5_summary_{candidate_round(name)}.json").read_text(encoding="utf-8"))
    return {"name": name, "program": path.name, "source": source, "parameters": params,
            "note": result_note(name, summary) if source != COMPLETION_SOURCE else None,
            "iou": row.get("iou"), "fit_mm": fit_to_measurements_mm(row), "ground_truth": ground_truth_error(name, row)}


def capture_fit_png(name):
    """The photo seen from straight above (as the IoU compares it) with the result's silhouette outline.

    The photo is rectified like the part mask the run compared against (3_part_mask_topdown.png,
    0.1 mm per pixel), both are turned to the IoU's canonical pose (centroid centered, main axis
    horizontal, best of the 0/180 degree and mirrored variants), and the result's outline is drawn
    on top. PNG bytes.
    """
    folder = run_dir(name)
    _cached_card_mask(folder, load_photo(_photo(folder)))  # makes sure 3_mask_card.png exists
    photo = topdown_photo(folder)
    reference = cv2.imread(str(folder / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0

    # The program the search chose (not an applied completion: that one differs from the photo on purpose).
    row = _result_row(name)
    if not row:
        raise FileNotFoundError("this run has no result program")
    path = _program_path(name, candidate_round(name), row["file"])
    mask_path = next((p for p in (path.with_suffix(".default.mask.npy"), path.with_suffix(".default.mask.png"))
                      if p.exists()), None)
    if mask_path is None:
        raise FileNotFoundError("no saved silhouette for the result program")
    silhouette = np.load(mask_path) if mask_path.suffix == ".npy" else cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE) > 0
    alignment = aligned_iou(reference, MM_PER_PIXEL, silhouette, MM_PER_PIXEL)

    # The photo goes through the reference mask's canonical transform (scale 1: both at 0.1 mm/px).
    size = alignment.reference.shape[0]
    cx, cy, angle = _centroid_and_angle(reference)
    linear = np.array([[np.cos(angle), np.sin(angle)], [-np.sin(angle), np.cos(angle)]])
    offset = np.array([(size - 1) / 2] * 2) - linear @ np.array([cx, cy])
    canonical = cv2.warpAffine(photo, np.hstack([linear, offset[:, None]]), (size, size))

    contours, _ = cv2.findContours(alignment.candidate.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    view = cv2.cvtColor(canonical, cv2.COLOR_RGB2BGR)
    cv2.drawContours(view, contours, -1, (43, 106, 255), 3, cv2.LINE_AA)  # BGR of the selected orange
    ys, xs = np.nonzero(alignment.reference | alignment.candidate)
    margin = 40
    crop = view[max(ys.min() - margin, 0):ys.max() + margin, max(xs.min() - margin, 0):xs.max() + margin]
    return cv2.imencode(".png", crop)[1].tobytes()


def _pixels(points):
    return [[round(float(x), 1), round(float(y), 1)] for x, y in points]


def is_sample(name):
    """True when the run resolves to a folder inside samples/ (a committed example)."""
    return run_dir(name).parent == SAMPLES_DIR.resolve()


# Readable names for the committed samples (shape + appearance or state); the folder name stays the run's
# id in URLs and is shown as a tooltip. Other runs are shown by their folder name.
SAMPLE_TITLES = {
    "A_light": "Plate, 4 holes",
    "A_light_repair": "Plate, 4 holes · broken candidates",
    "A_torn_fallback": "Plate, 4 holes · torn edges",
    "A_brushed": "Plate, 4 holes · brushed metal",
    "C_wood": "Flat L, 2 holes · wood",
    "D_black_plastic": "Tabbed plate, 2 holes · black plastic",
    "D_tab_broken": "Tabbed plate · snapped tab",
    "E_glossy_white": "Plate, square hole and slot · glossy white",
    "live-20261103-224610-c8b8df": "Cardboard plate, broken corner",
}


def display_name(name):
    """The run's readable name: a sample's title when it resolves to samples/, else its folder name."""
    try:
        return SAMPLE_TITLES.get(name, name) if is_sample(name) else name
    except FileNotFoundError:
        return name


def run_kind(name):
    """"Real photo" or "Synthetic": live-* runs are uploaded photos, everything else is a rendered scene.
    The one source for the gallery badge and the run chip."""
    return "Real photo" if name.startswith("live-") else "Synthetic"


def info(name):
    """Light data for screen 1: the saved click, the photo size (no mask decoding) and the run's kind."""
    folder = run_dir(name)
    attempts = json.loads((folder / "2_sam_attempts.json").read_text(encoding="utf-8"))
    height, width = cv2.imread(str(_photo(folder)), cv2.IMREAD_GRAYSCALE).shape
    return {"name": name, "click_px": attempts.get("click"), "image_size": [width, height],
            "kind": run_kind(name), "sample": is_sample(name), "title": display_name(name)}


@functools.lru_cache(maxsize=16)
def analysis(name):
    """Data for screens 1-2: photo size, click, card corners, part outline and holes (pixels), table (mm)."""
    folder = run_dir(name)
    measurements = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))
    attempts = json.loads((folder / "2_sam_attempts.json").read_text(encoding="utf-8"))
    image = load_photo(_photo(folder))
    card_mask = _cached_card_mask(folder, image)
    card_long_px = card_long_edge_px(card_mask)
    tilt = card_tilt(card_mask)
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
        holes.append({"shape": shape, "size": f"{size} mm", "label": f"{shape} {size} mm",
                      "contour_px": _pixels(points), "center_px": _pixels([points.mean(axis=0)])[0]})

    table = measurements["table"]
    return {
        "name": name,
        "image_size": list(image.size),
        "click_px": attempts.get("click"),
        "part_found_by": attempts.get("chosen_source"),
        "card_corners_px": _pixels(card_corners(largest_contour(card_mask))),
        "card_edge_differences_pct": [round(float(d) * 100, 2) for d in differences],
        "scale_used": scale_used,
        "card_mm_per_pixel": round(float(scales["simple"][0, 0]), 5),  # mean card scale
        "card_long_px": round(card_long_px, 1),
        "resolution_warning": resolution_warning(card_long_px),
        "card_tilt_pct": round(float(tilt) * 100, 2),
        "tilt_warning": tilt_warning(tilt),
        "hole_method": method,
        "outline_px": _pixels(contours[outer].reshape(-1, 2)),
        "outline_mm": {"length": table["outline"]["length_mm"], "width": table["outline"]["width_mm"],
                       "corners": table["outline"]["vertex_count"]},
        "holes": holes,
        "table": {"outline": {k: table["outline"][k] for k in ("length_mm", "width_mm", "vertex_count")},
                  "hole_count": table["hole_count"],
                  "holes": [{k: v for k, v in h.items() if k not in ("polygon_mm",)} for h in table["holes"]]},
    }
