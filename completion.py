"""Completion suggestions with Muse Wonder for parts that look broken or incomplete.

Only runs when break_cues.py finds evidence (Wonder is not asked otherwise). Wonder sees the cues,
the part seen from straight above (photo rectified at 0.1 mm per pixel), the winning program and its
silhouette. It answers whether the part is broken, what to add (a parameter or a feature) and why,
and writes the completed program, keeping the winner's parameters. The completion is a separate
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
from e2e_pipeline import MM_PER_PIXEL, pixel_to_mm_scales, save_json
from homography import rectify_image
from repair import ask_wonder, make_client
from sam_client import load_photo

FOLDER = "6_completion"
MAX_REMOVED_SHARE = 0.03  # a completion may cut new holes, but remove at most this share of the winner's volume

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
1. The part seen from straight above (the photo, rectified, 0.1 mm per pixel).
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

Reply in this format and nothing else:
BROKEN: yes | no
SUGGESTION: <one sentence: what to add or change, naming the parameter or feature>
RATIONALE: <one to three sentences, grounded in the cues>
```python
<the completed program>
```"""


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
            "rationale": field("RATIONALE"), "code": extract_python_block(text)}


def suggest_completion(out, winner_path, winner_mask, builder, client=None, cues=None):
    """Ask Wonder for a completion of the run's result when break cues exist; check it; save and return it.

    winner_mask: the winner's top-view silhouette (bool array). builder: webapp.builder.Builder (compare).
    Returns None when there are no cues (Wonder is not called).
    """
    out = Path(out)
    table = json.loads((out / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    cues = cues if cues is not None else find_break_cues(table)
    if not cues["break_likely"]:
        return None
    folder = out / FOLDER
    folder.mkdir(exist_ok=True)
    cv2.imwrite(str(folder / "photo_topdown.png"), cv2.cvtColor(topdown_photo(out), cv2.COLOR_RGB2BGR))
    cv2.imwrite(str(folder / "winner_silhouette.png"), winner_mask.astype(np.uint8) * 255)
    winner_code = Path(winner_path).read_text(encoding="utf-8")
    prompt = PROMPT.format(cues=json.dumps(cues["cues"], indent=2), code=winner_code.strip())
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")

    try:
        response, seconds = ask_wonder(client or make_client(), prompt,
                                       [folder / "photo_topdown.png", folder / "winner_silhouette.png"])
    except Exception as error:
        response, seconds = {"error": f"{type(error).__name__}: {error}"}, None
    save_json(folder / "response.json", response)
    usage_ledger.record_response(out, usage_ledger.WONDER, "completion", response, seconds)
    answer = parse_answer(None if "error" in response else response["choices"][0]["message"]["content"])
    result = {"cues": cues["cues"], "winner": Path(winner_path).name, "broken": answer["broken"],
              "suggestion": answer["suggestion"], "rationale": answer["rationale"], "seconds": seconds,
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
