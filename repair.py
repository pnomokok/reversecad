"""Repair loop with Muse Wonder: when no candidate passes, or the best one is under the IoU threshold.

Wonder sees the measurements (the model's view), the part's top-down mask and, for the best 2-3
failed candidates, their code, their XOR difference image and why they failed (repair_inputs.py).
It explains briefly what is wrong and writes one corrected program with partkit, under the same rules
as the candidates. The program goes through the same checks (compile, silhouette, IoU, deviation
limits, topology when the truth is known). At most MAX_ROUNDS rounds; each round also shows the
previous repair if it failed. Every call goes to the run's usage ledger.
"""
import base64
import os
import re
import time
from pathlib import Path

import cv2
from dotenv import load_dotenv
from openai import OpenAI

import usage_ledger
from candidates import build_prompt, extract_python_block
from e2e_pipeline import check_program, save_json
from model_view import model_view
from repair_inputs import build_repair_request, crop_to_content, failure_reasons, pick_failed

BASE_URL = "https://api.meta.ai/v1"
MODEL = usage_ledger.WONDER
REASONING_EFFORT = "medium"
MAX_ROUNDS = 2
IOU_THRESHOLD = 0.90  # the success criterion for the silhouette (CLAUDE.md)
IMAGE_WIDTH = 640  # images are cropped to their content and scaled to this width
REPAIR_NUMBER = 100  # a passing repaired program is candidate 101 (round 1) or 102 (round 2)

INTRODUCTION = """You repair CadQuery programs for a flat, prismatic part measured from a photo.
Candidate programs written by another model failed the checks. Find out what is wrong and write one
corrected program.

Images, in order:
1. The part's top-down silhouette from the photo: white = part, black = background.
{xor_list}
Each XOR image overlays a failed candidate's silhouette on the photo's (aligned as the checker does):
white = in both, red = in the photo but missing from the program, blue = in the program but not in the photo.

{candidates}
"""

ANSWER_FORMAT = """- Reply in this format and nothing else:
DIAGNOSIS: <one to three sentences: what is wrong in the failed programs, by name>
```python
<the corrected program>
```"""


def needs_repair(summary, threshold=IOU_THRESHOLD):
    """True when no candidate passed, or the winner's IoU is below the threshold."""
    winner = summary.get("winner")
    return winner is None or winner.get("iou", 0) < threshold


def make_client():
    load_dotenv()
    api_key = os.getenv("MODEL_API_KEY")
    if not api_key:
        raise RuntimeError("MODEL_API_KEY is missing from .env")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def _data_url(path):
    image = crop_to_content(cv2.imread(str(path), cv2.IMREAD_UNCHANGED))
    height = max(1, round(image.shape[0] * IMAGE_WIDTH / image.shape[1]))
    image = cv2.resize(image, (IMAGE_WIDTH, height), interpolation=cv2.INTER_AREA)
    return "data:image/png;base64," + base64.b64encode(cv2.imencode(".png", image)[1].tobytes()).decode("ascii")


def repair_prompt(request, table, thickness, no_code_reasons=()):
    """The candidates' rules (build_prompt) with the repair introduction and answer format."""
    shown = [c for c in request["candidates"]]
    xor_list = "\n".join(f"{i}. XOR image of {c['name']}." for i, c in
                         enumerate([c for c in shown if c["xor_image"]], 2))
    parts = []
    for c in shown:
        parts.append(f"Failed program {c['name']}" + (f" (IoU {c['iou']:.4f})" if c["iou"] is not None else "")
                     + ":\nWhy it failed:\n" + "\n".join(f"- {r}" for r in c["reasons"])
                     + f"\n```python\n{c['code'].strip()}\n```")
    if no_code_reasons:
        parts.append("Candidates that returned no program at all:\n" + "\n".join(f"- {r}" for r in no_code_reasons))
    rules = build_prompt(model_view(table), thickness)
    rules = rules.split("Measurement table in millimeters", 1)[1]  # drop the candidates' own introduction
    rules = rules.replace("- Reply with a single ```python code block and nothing else.", ANSWER_FORMAT)
    return INTRODUCTION.format(xor_list=xor_list or "(no XOR images: no failed program could be drawn)",
                               candidates="\n\n".join(parts)) + "\nMeasurement table in millimeters" + rules


def ask_wonder(client, prompt, image_paths):
    """One Chat Completions call; returns (response dict, seconds)."""
    started = time.perf_counter()
    content = [{"type": "text", "text": prompt}]
    content += [{"type": "image_url", "image_url": {"url": _data_url(p)}} for p in image_paths]
    response = client.chat.completions.create(model=MODEL, reasoning_effort=REASONING_EFFORT,
                                              messages=[{"role": "user", "content": content}])
    return response.model_dump(), round(time.perf_counter() - started, 1)


def parse_answer(text):
    """(diagnosis, code) from Wonder's answer; either may be None."""
    match = re.search(r"DIAGNOSIS:\s*(.*?)(?:```|$)", text or "", re.DOTALL)
    return (match.group(1).strip() if match else None), extract_python_block(text)


def passed(row):
    return "iou" in row and row["deviation_ok"] and row.get("topology_ok") is not False


def repaired_row(repaired):
    """The passing repaired program's row, numbered REPAIR_NUMBER + round (shown as R1, R2)."""
    return repaired["result"]


def repair_loop(out, table, reference, mask_path, rows, thickness=3.0, truth=None, render=None, emit=None,
                rounds=MAX_ROUNDS, client=None):
    """Run up to `rounds` repair rounds; returns {"passed", "rounds": [...], "result": row or None}.

    rows are checked candidate rows (with their private _alignment); out is the run folder.
    """
    out = Path(out)
    client = client or make_client()
    tried = list(rows)
    no_code = [r["error"] for r in rows if "error" in r and not Path(r["file"]).exists()]
    history = []
    for number in range(1, rounds + 1):
        folder = out / f"repair_round_{number}"
        request = build_repair_request(folder, table, mask_path, pick_failed(tried))
        prompt = repair_prompt(request, table, thickness, no_code)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        images = [folder / request["mask_image"]] + [folder / c["xor_image"] for c in request["candidates"] if c["xor_image"]]
        if emit:
            emit({"type": "progress", "message": f"repair round {number} · Muse Wonder"})
        try:
            response, seconds = ask_wonder(client, prompt, images)
        except Exception as error:
            response, seconds = {"error": f"{type(error).__name__}: {error}"}, None
        save_json(folder / "response.json", response)
        usage_ledger.record_response(out, MODEL, f"repair round {number}", response, seconds)
        text = None if "error" in response else response["choices"][0]["message"]["content"]
        diagnosis, code = parse_answer(text)
        path = folder / "repaired.py"
        if "error" in response:
            row = {"file": str(path), "error": f"request failed: {response['error']}"}
        elif code is None:
            row = {"file": str(path), "error": f"no python code block (finish={response['choices'][0]['finish_reason']})"}
        else:
            path.write_text(code, encoding="utf-8")
            row = check_program(path, reference, truth, table, render=render)
        usage = (response.get("usage") or {}) if isinstance(response, dict) else {}
        entry = {"round": number, "diagnosis": diagnosis, "passed": passed(row), "iou": row.get("iou"),
                 "reasons": failure_reasons(row), "seconds": seconds,
                 "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                 "cost_usd": usage_ledger.cost(MODEL, usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0, 0)}
        history.append(entry)
        save_json(folder / "result.json", entry)
        if emit:
            emit({"type": "repair", **entry})
        if entry["passed"]:
            result = {k: v for k, v in row.items() if not k.startswith("_")}
            result.update({"candidate": REPAIR_NUMBER + number, "label": f"R{number}", "diagnosis": diagnosis})
            return {"passed": True, "rounds": history, "result": result}
        tried = [{**row, "candidate": f"repair {number}"}] + tried  # the next round sees this attempt too
    return {"passed": False, "rounds": history, "result": None}
