"""Completion suggestions with Muse Wonder for parts that look broken or incomplete.

Only runs when break_cues.py finds evidence (Wonder is not asked otherwise). Wonder sees the cues,
the part seen from straight above (photo rectified at 0.1 mm per pixel), the winning program and its
silhouette (or, with source="mask", the part's mask instead of the photo). It answers whether the
part is broken, what to add (a parameter or a feature) and why, which added numbers are measured,
estimated (with a question for the user) or optional (a feature nothing shows, off by default, with
a question), and writes the completed program, keeping the winner's parameters. The completion is a separate
candidate: it must build, and compared with the winner it may add material and cut holes but must not
take away the measured part (checked with CadQuery booleans: what it adds and removes, in mm^3).
Outputs go to <run>/6_completion/.
"""
import json
import re
from pathlib import Path

import cv2
import numpy as np

import usage_ledger
from break_cues import find_break_cues
from candidates import check_code, extract_python_block
from design_intent import parameters as program_parameters
from e2e_pipeline import MM_PER_PIXEL, pixel_to_mm_scales, save_json
from homography import rectify_image
from repair import ask_wonder, make_client
from sam_client import load_photo

FOLDER = "6_completion"
MAX_REMOVED_SHARE = 0.03  # a completion may cut new holes, but remove at most this share of the winner's volume
HOLE_MATCH_MM = 0.5  # a claimed-measured hole position/diameter must match a measured hole this closely
PARAM_MATCH = 1e-9  # a claimed-measured winner parameter is copied exactly

PROMPT = """A flat, prismatic part was measured from a photo and modeled as a CadQuery program (below).
The program matches the photo. But deterministic code found cues that the part itself may be broken
or incomplete, so the photo may not show the part as it was designed.

Cues (mm; [u, v] from the center of the measured outline's bounding rectangle, u along its length,
v across; the program's X, Y are the same axes, but its origin may differ slightly):
{cues}

What the cues mean:
- rough_edge: an outline edge that zigzags like a break (designed edges are straight or round).
- missing_material: the part is nearly symmetric, and this region of its mirror image is missing,
  next to a rough edge.
- missing_hole: equal holes form a mirror pattern with a gap here, where there is material.
- partial_hole: the pattern expects a hole here and the outline follows part of its circle.

Images, in order:
1. {first_image}
2. The program's top-view silhouette: white = part, black = background.

The program:
```python
{code}
```

Decide whether the part is broken or incomplete. If it is, say how the intact part was most likely
designed (for example: restore the broken corner, add the missing hole, restore a snapped-off tab with
its hole) and write the completed program:
- keep every parameter of the given program with its name and default; add new named parameters for
  what you add (for example tab_length, tab_width, tab_hole_diameter);
- keep the measured part: only add material or cut holes where the cues point;
- use the patterns and symmetry the program already has (shared hole diameter, edge margins);
- same rules as the given program: one function build_part, X = u, Y = v, bottom face at Z = 0,
  `import cadquery as cq`, `import partkit as pk` and `import math` only, no show_object or I/O.
If it is not broken, answer BROKEN: no and no program.

Say which numbers are measured and which are not. For every dimension or feature you add, give one
entry in PARTS (a JSON list on one line):
  {{"name": "<its parameter in your program>", "value": <its default>, "basis": "measured" | "estimated" | "optional",
    "evidence": "<measured: the cue or existing parameter that gives it>", "question": "<estimated, optional: a short question to the user>"}}
- measured: the cues or the existing parameters fix it (for example a tab's width = the rough edge's length).
- estimated: nothing in the photo measures it (for example how far a snapped-off tab stuck out); give your best
  value and ask for the real one.
- optional: a feature nothing in the photo shows, but which the intact part may have had (for example a hole in a
  snapped-off tab). Put it in the program behind a numeric parameter whose default 0 leaves it out, give the value
  you would suggest in "value", and ask whether to add it.

Reply in this format and nothing else:
BROKEN: yes | no
SUGGESTION: <one sentence: what to add or change, naming the parameter or feature>
RATIONALE: <one to three sentences, grounded in the cues>
PARTS: <the JSON list>
```python
<the completed program>
```"""

FIRST_IMAGE = {
    "photo": "The part seen from straight above (the photo, rectified, 0.1 mm per pixel).",
    "mask": "The part's top-down silhouette from the photo (0.1 mm per pixel): white = part, black = background.",
}
DEFAULT_INPUT = "mask"  # what Wonder sees of the part; the mask did as well as the photo on all 4 broken parts (compare_completion_inputs.py), so the photo stays home


def topdown_photo(folder):
    """The run's photo seen from straight above around the part (RGB, 0.1 mm per pixel), as the pipeline
    rectified the part mask (3_part_mask_topdown.png has the same size and position)."""
    folder = Path(folder)
    measurements = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))
    table = measurements["table"]
    photo_path = next(p for p in (folder / "1_scene.png", folder / "1_scene.jpg") if p.exists())
    image = load_photo(photo_path)
    card = cv2.imread(str(folder / "3_mask_card.png"), cv2.IMREAD_GRAYSCALE) > 0
    pixel_to_mm = pixel_to_mm_scales(card)[0][measurements["scale_used"]]
    center = np.array(table["center_on_table_mm"])
    half = table["outline"]["length_mm"] / 2 + 8  # the same region the pipeline rectified
    photo, _ = rectify_image(np.asarray(image), pixel_to_mm, (*(center - half), *(center + half)), MM_PER_PIXEL)
    return photo


def parse_answer(text):
    """{"broken", "suggestion", "rationale", "code"} from Wonder's answer."""
    def field(name):
        match = re.search(rf"{name}:\s*(.*?)(?:\n[A-Z]+:|```|$)", text or "", re.DOTALL)
        return match.group(1).strip() if match else None

    broken = (field("BROKEN") or "").lower()
    return {"broken": broken.startswith("yes") if broken else None, "suggestion": field("SUGGESTION"),
            "rationale": field("RATIONALE"), "parts": _parts(text), "code": extract_python_block(text)}


def _parts(text):
    """The PARTS list: entries with a name, a numeric value and a basis of measured, estimated or optional."""
    match = re.search(r"PARTS:\s*(\[.*?\])\s*(?:\n[A-Z]+:|```|$)", text or "", re.DOTALL)
    try:
        entries = json.loads(match.group(1)) if match else []
    except json.JSONDecodeError:
        return []
    return [{"name": str(e["name"]), "value": float(e["value"]), "basis": e["basis"],
             "evidence": e.get("evidence"), "question": e.get("question")}
            for e in entries if isinstance(e, dict) and e.get("basis") in ("measured", "estimated", "optional")
            and isinstance(e.get("value"), (int, float)) and e.get("name")]


def _hole_xy(hole):
    """A table hole's center as (x, y); the table stores it as a pair or as "u v"."""
    center = hole.get("center_from_part_center_mm")
    try:
        x, y = center if isinstance(center, list) else center.split()
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _measured_backed(part, by_name, centers, diameters, winner_params):
    """Whether a "measured" claim reappears in the measurements: an x/y pair at a measured
    hole center, a winner parameter's own default, or a measured hole diameter."""
    name, value = part["name"], part["value"]
    for x_suffix, y_suffix in (("_x", "_y"), ("_u", "_v")):
        if name.endswith((x_suffix, y_suffix)):
            mate = by_name.get(name[:-2] + (y_suffix if name.endswith(x_suffix) else x_suffix))
            if mate is None or not isinstance(mate.get("value"), (int, float)):
                return False  # a lone coordinate proves no measured hole
            x, y = (value, mate["value"]) if name.endswith(x_suffix) else (mate["value"], value)
            return any(float(np.linalg.norm(np.array([x, y]) - np.array(center))) <= HOLE_MATCH_MM
                       for center in centers)
    if any(abs(value - default) <= PARAM_MATCH for default in winner_params.values()):
        return True
    return any(abs(value - diameter) <= HOLE_MATCH_MM for diameter in diameters)


def verify_parts(parts, table, winner_params):
    """The PARTS list with unverifiable "measured" claims demoted to "estimated".

    Wonder labels each added value, but a mirrored hole position is still a guess even when
    its mirror source was measured. Demotion is one way only (estimated/optional are never
    touched), so re-checking stored runs is safe; demoted entries keep "demoted_from".
    """
    centers = [xy for xy in (_hole_xy(hole) for hole in table.get("holes", [])) if xy is not None]
    diameters = [hole["diameter_mm"] for hole in table.get("holes", [])
                 if isinstance(hole.get("diameter_mm"), (int, float))]
    by_name = {part["name"]: part for part in parts}
    checked = []
    for part in parts:
        entry = dict(part)
        if part.get("basis") == "measured" and not _measured_backed(part, by_name, centers, diameters,
                                                                    winner_params):
            entry["basis"] = "estimated"
            entry["demoted_from"] = "measured"
        checked.append(entry)
    return checked


def verified_stored_parts(run_folder, data):
    """Stored PARTS with measured claims re-checked (old runs keep Wonder's raw labels).

    Falls back to the stored list when the table or the winner program cannot be read.
    """
    try:
        table = json.loads((Path(run_folder) / "3_measurements.json").read_text(encoding="utf-8"))["table"]
        if not data.get("winner"):
            return data.get("parts")
        winner = next(Path(run_folder).glob("**/" + data["winner"]))
        winner_params = {name: value for name, value in program_parameters(winner.read_text(encoding="utf-8"))
                         if isinstance(value, (int, float)) and not isinstance(value, bool)}
    except (OSError, ValueError, KeyError, StopIteration):
        return data.get("parts")
    return verify_parts(data.get("parts") or [], table, winner_params)


def suggest_completion(out, winner_path, winner_mask, builder, client=None, cues=None, source=DEFAULT_INPUT,
                       folder_name=FOLDER):
    """Ask Wonder for a completion of the run's result when break cues exist; check it; save and return it.

    winner_mask: the winner's top-view silhouette (bool array). builder: webapp.builder.Builder (compare).
    source: what Wonder sees of the part, the rectified "photo" or only its "mask". Returns None when
    there are no cues (Wonder is not called).
    """
    out = Path(out)
    table = json.loads((out / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    cues = cues if cues is not None else find_break_cues(table)
    if not cues["break_likely"]:
        return None
    folder = out / folder_name
    folder.mkdir(exist_ok=True)
    if source == "photo":
        part_image = folder / "photo_topdown.png"
        cv2.imwrite(str(part_image), cv2.cvtColor(topdown_photo(out), cv2.COLOR_RGB2BGR))
    else:
        part_image = folder / "mask_topdown.png"
        cv2.imwrite(str(part_image), cv2.imread(str(out / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE))
    cv2.imwrite(str(folder / "winner_silhouette.png"), winner_mask.astype(np.uint8) * 255)
    winner_code = Path(winner_path).read_text(encoding="utf-8")
    prompt = PROMPT.format(cues=json.dumps(cues["cues"], indent=2), code=winner_code.strip(),
                           first_image=FIRST_IMAGE[source])
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")

    try:
        response, seconds = ask_wonder(client or make_client(), prompt, [part_image, folder / "winner_silhouette.png"])
    except Exception as error:
        response, seconds = {"error": f"{type(error).__name__}: {error}"}, None
    save_json(folder / "response.json", response)
    usage_ledger.record_response(out, usage_ledger.WONDER, f"completion ({source})", response, seconds)
    answer = parse_answer(None if "error" in response else response["choices"][0]["message"]["content"])
    winner_params = {name: value for name, value in program_parameters(winner_code)
                     if isinstance(value, (int, float)) and not isinstance(value, bool)}
    answer["parts"] = verify_parts(answer["parts"], table, winner_params)
    result = {"cues": cues["cues"], "winner": Path(winner_path).name, "broken": answer["broken"],
              "suggestion": answer["suggestion"], "rationale": answer["rationale"], "parts": answer["parts"],
              "input": source, "seconds": seconds, "usage": response.get("usage"),
              "error": response.get("error"), "program": None, "check": None, "status": "suggested"}

    if answer["code"]:
        program = folder / "completed.py"
        program.write_text(answer["code"], encoding="utf-8")
        result["program"] = program.name
        result["check"] = check_completion(program, winner_path, folder, builder)
    result["valid"] = bool(result["check"] and result["check"]["ok"])
    save_json(folder / "completion.json", result)
    return result


def check_completion(program, winner_path, folder, builder):
    """Build the completion against the winner: it must build, change something, and keep the winner's material."""
    problems = check_code(Path(program).read_text(encoding="utf-8"))
    if problems:
        return {"ok": False, "reasons": problems}
    report_path = folder / "compare.json"
    error = builder.compare(program, winner_path, folder / "added.stl", folder / "removed.stl", report_path)
    if error:
        return {"ok": False, "reasons": [error]}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reasons = []
    if report["added_volume_mm3"] + report["removed_volume_mm3"] < 1:
        reasons.append("the completion does not change the part")
    if report["removed_volume_mm3"] > MAX_REMOVED_SHARE * report["base_volume_mm3"]:
        reasons.append(f"it removes {report['removed_volume_mm3']} mm^3 of the measured part")
    return {"ok": not reasons, "reasons": reasons, **report}
