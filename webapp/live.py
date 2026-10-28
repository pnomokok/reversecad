"""Live mode: run the pipeline on an uploaded photo, reporting progress as events.

Live runs are saved exactly like the replayed ones (outputs/e2e/live-<time>-<id>/), so screens
4-5 and later replays work on them unchanged. The steps reuse the pipeline's own functions
(find_masks, measure, check_program); nothing about the measurement changes here. Each job takes
an emit(event) callback; the server turns events into server-sent events.

Data leaves the machine only as in the pipeline: the photo goes to SAM (Meta); if the click finds
nothing, also to Muse Spark Open for name suggestions; the candidate requests send only the part's
top-down mask, never the photo.
"""
import io
import json
import re
import time
import uuid

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

import usage_ledger
from baseline_cad import baseline_code
from break_cues import find_break_cues
from completion import suggest_completion
from candidates import extract_python_block, iter_candidates
from e2e_pipeline import EARLY_STOP_AGREEING, SamCache, passed_every_check, check_program, find_masks, measure, save_json, search_settled
from model_view import model_view
from repair import needs_repair, repair_loop, repaired_row
from sam_client import load_photo
from webapp import replay

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
LIVE_NAME = re.compile(r"^live-\d{8}-\d{6}-[0-9a-f]{6}$")
ROUND = "candidates_arcs_effort_medium"  # same folder name as the default (medium) pipeline round


def live_dir(name):
    folder = replay.RUNS_DIR / name
    if not LIVE_NAME.match(name) or not (folder / "1_scene.png").exists():
        raise FileNotFoundError(f"no live run named {name!r}")
    return folder


def save_upload(data):
    """Store an uploaded photo upright (EXIF orientation applied) as PNG, which drops its EXIF data."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(f"the photo is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as error:
        raise ValueError(f"not a readable image: {error}") from error
    name = f"live-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    folder = replay.RUNS_DIR / name
    folder.mkdir(parents=True)
    image.save(folder / "1_scene.png")
    return {"name": name, "image_size": list(image.size)}


class ProgressSam(SamCache):
    """SamCache that reports each SAM request (they take seconds, mostly decoding the mask text)."""

    def __init__(self, folder, emit):
        super().__init__(folder)
        self.emit = emit

    def segment(self, image, prompt, tag="", key=None):
        what = "the clicked part" if key == "point" else repr(prompt)
        where = " (zoomed in on the part)" if tag == "crop_" else ""
        self.emit({"type": "progress", "message": f"SAM: looking for {what}{where}…"})
        return super().segment(image, prompt, tag, key)


def measure_job(name, click, emit):
    """Screens 1-2 live: find the card and the clicked part, measure, then send the overlay data."""
    folder = live_dir(name)
    for stale in ("point.txt", "crop_point.txt"):  # cached under one name, so a new click must not reuse them
        (folder / "sam" / stale).unlink(missing_ok=True)
    image = load_photo(folder / "1_scene.png")
    sam = ProgressSam(folder / "sam", emit)
    card, part, crop_mask, _ = find_masks(folder, image, sam, click, folder / "1_scene.png")
    emit({"type": "progress", "message": "Measuring the outline and the holes…"})
    measure(folder, image, card, part, crop_mask)
    replay.analysis.cache_clear()
    emit({"type": "analysis", **replay.analysis(name)})


def candidates_job(name, count, thickness, render, emit, builder=None):
    """Screen 3 live: ask for candidates, check each as it arrives, then pick the result.

    render(path, mm_per_pixel) -> (mask, error) builds a silhouette (the web app's build process).
    With the builder, a part that shows break cues also gets a completion suggestion (Muse Wonder).
    """
    folder = live_dir(name)
    table = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    reference = cv2.imread(str(folder / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0
    round_dir = folder / ROUND
    round_dir.mkdir(exist_ok=True)
    emit({"type": "progress", "message": f"Asking Muse Spark Open for {count} candidates…"})

    rows, stopped_early = [], False
    requests = iter_candidates(model_view(table), folder / "3_part_mask_topdown.png", count, thickness=thickness)
    for prompt, index, response in requests:
        (round_dir / f"cand_{index}_prompt.txt").write_text(prompt, encoding="utf-8")
        save_json(round_dir / f"cand_{index}_response.json", response)
        usage_ledger.record_response(folder, usage_ledger.SPARK_OPEN, f"candidate {index}", response)
        path = round_dir / f"cand_{index}.py"
        code = None if "error" in response else extract_python_block(response["choices"][0]["message"]["content"])
        if "error" in response:
            row = {"file": str(path), "error": f"request failed: {response['error']}"}
        elif code is None:
            row = {"file": str(path), "error": "no python code block (finish="
                                               f"{response['choices'][0]['finish_reason']})"}
        else:
            path.write_text(code, encoding="utf-8")
            row = check_program(path, reference, None, table, render=render)
        row = {"candidate": index, "style": response.get("style"), **row}
        rows.append(row)
        emit(replay.candidate_event(name, row))
        if search_settled(rows) and len(rows) < count:  # decided at the consultation, 2026-10-28
            stopped_early = True
            requests.close()  # cancels the requests that have not started
            emit({"type": "progress", "message": f"{EARLY_STOP_AGREEING} candidates passed with the same shape: "
                                                 f"search stopped after {len(rows)} of {count}."})
            break

    baseline_path = round_dir / "baseline.py"
    baseline_path.write_text(baseline_code(table, thickness), encoding="utf-8")
    baseline = check_program(baseline_path, reference, None, table, render=render)
    summary = {**_summary(rows, baseline), "requested": count, "stopped_early": stopped_early}
    if needs_repair(summary):  # no candidate passed every check
        repaired = repair_loop(folder, table, reference, folder / "3_part_mask_topdown.png", rows,
                               thickness=thickness, render=render, emit=emit)
        summary["repair"] = repaired
        if repaired["passed"]:
            row = repaired_row(repaired)
            emit(replay.candidate_event(name, row))
            summary.update({"winner": row, "result": row, "result_source": "repair · Muse Wonder"})
    result = summary["result"]
    if builder and result and summary["result_source"] != replay.FALLBACK_SOURCE:
        cues = find_break_cues(table)
        if cues["break_likely"]:  # Wonder is asked only when code found evidence of a break
            emit({"type": "progress", "message": "Possible break: asking Muse Wonder for a completion…"})
            program = Path(result["file"])
            suggest_completion(folder, program, np.load(program.with_suffix(".default.mask.npy")), builder, cues=cues)
    summary["usage"] = usage_ledger.summarize(folder)
    save_json(folder / f"5_summary_{ROUND}.json", summary)
    emit(replay.done_event(summary, ROUND, replay.result_note(name, summary), name))


def _summary(rows, baseline):
    """Same fields as e2e_pipeline.validate writes, so replay reads live runs the same way."""
    def clean(row):
        return {k: v for k, v in row.items() if not k.startswith("_")} if row else None

    compiled = [r for r in rows if "iou" in r]
    eligible = [r for r in compiled if passed_every_check(r)]
    best = max(eligible, key=lambda r: (round(r["iou"], 3), -r["parameter_count"])) if eligible else None
    if best is not None:
        result, source = clean(best), "candidate"
    elif "iou" in baseline:
        result, source = clean(baseline), "fallback: measured shape, no design intent"
    else:
        result, source = None, "none: no candidate and no baseline compiled"
    return {"compiled": len(compiled), "within_deviation": len(eligible), "candidate_count": len(rows),
            "winner": clean(best), "result": result, "result_source": source, "baseline": clean(baseline),
            "candidates": [clean(r) for r in sorted(rows, key=lambda r: r["candidate"])]}


def repair_again_job(name, builder, emit):
    """"Try repair again" on a saved run where no candidate passed: rebuild the failed candidates (for their
    difference images), run the Muse Wonder repair loop, and save the result into the run's summary."""
    round_name = replay.candidate_round(name)
    folder = replay.run_dir(name)
    summary_path = folder / f"5_summary_{round_name}.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    table = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))["table"]
    reference = cv2.imread(str(folder / "3_part_mask_topdown.png"), cv2.IMREAD_GRAYSCALE) > 0
    emit({"type": "progress", "message": "Rebuilding the failed candidates for Muse Wonder…"})
    rows = []
    for row in summary["candidates"]:
        program = replay._program_path(name, round_name, row["file"])
        rows.append({**row, **check_program(program, reference, None, table, render=builder.silhouette)}
                    if program.exists() and "error" not in row else row)
    repaired = repair_loop(folder, table, reference, folder / "3_part_mask_topdown.png", rows,
                           render=builder.silhouette, emit=emit)
    summary["repair"] = repaired
    if repaired["passed"]:
        row = repaired_row(repaired)
        emit(replay.candidate_event(name, row))
        summary.update({"winner": row, "result": row, "result_source": "repair · Muse Wonder"})
    summary["usage"] = usage_ledger.summarize(folder)
    save_json(summary_path, summary)
    emit(replay.done_event(summary, round_name, replay.result_note(name, summary), name))
