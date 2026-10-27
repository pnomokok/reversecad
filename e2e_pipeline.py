"""End-to-end pipeline for one scene: photo -> SAM masks -> measurements -> candidate
CadQuery code -> compile -> silhouette -> IoU and topology check -> best candidate.

Steps and their outputs (in the scene's output folder):
  1  scene image and ground truth
  2  Muse Spark Open suggests SAM prompts; all are tried, the most confident part mask wins;
     the part is cropped (with a margin) and segmented again to see small holes in more detail
  3  measurement tables from three hole methods (full SAM mask, cropped SAM mask, color),
     each compared with the truth; the cropped mask is used unless its holes look wrong
  4  candidate programs from Muse Spark Open
  5  compile, render, IoU, topology check, variety between candidates
SAM and Muse Spark Open answers are cached in the folder; delete them to ask again.
"""
import json
from pathlib import Path

import cv2
import numpy as np

from candidates import extract_python_block, generate_candidates
from homography import card_corners, card_homography, edge_differences, largest_contour, rectify_image
from iou import aligned_iou
from measure import CARD_LONG_MM, CARD_SHORT_MM
from overlay import draw_overlay
from part_measurements import check_topology, compare_to_truth, measure_part
from prompt_suggestions import suggest_part_prompts
from refine_holes import refine_holes
from render_silhouette import render_top_silhouette
from run_candidate import run_candidate
from sam_client import load_photo, make_client, parse_detections, segment

MM_PER_PIXEL = 0.1  # top-down resolution for masks, renders and IoU
CARD_PROMPTS = ["credit card", "card", "bank card"]
FALLBACK_PART_PROMPTS = ["metal plate", "plate", "flat metal part"]
CROP_MARGIN = 0.15  # crop margin as a share of the part's larger side
MIN_HOLE_ROUNDNESS = 0.85
MIN_HOLE_DIAMETER_MM = 1.5


def save_json(path, data):
    # numpy numbers (float32, int64) are not JSON types; .item() turns them into plain Python numbers.
    Path(path).write_text(json.dumps(data, indent=2, default=lambda o: o.item()), encoding="utf-8")


def mask_iou(a, b):
    union = np.count_nonzero(a | b)
    return float(np.count_nonzero(a & b) / union) if union else 0.0


def card_aspect_ok(mask):
    (_, (w, h), _) = cv2.minAreaRect(largest_contour(mask).astype(np.float32))
    return abs(max(w, h) / min(w, h) - CARD_LONG_MM / CARD_SHORT_MM) < 0.15


def holes_look_right(table):
    return all(h["roundness"] is not None and h["roundness"] >= MIN_HOLE_ROUNDNESS
               and h["diameter_mm"] >= MIN_HOLE_DIAMETER_MM for h in table["holes"])


class SamCache:
    """SAM calls with their raw answers cached as text files."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.client = None

    def segment(self, image, prompt, tag=""):
        path = self.folder / f"{tag}{prompt.replace(' ', '_')}.txt"
        if path.exists():
            return parse_detections(path.read_text(encoding="utf-8"), image.size)
        self.client = self.client or make_client()
        detections, raw_text = segment(self.client, image, prompt)
        path.write_text(raw_text, encoding="utf-8")
        return detections


def segment_crop(sam, image, part_mask, prompt):
    """Segment the part again inside a crop around it; return a full-size mask or None."""
    ys, xs = np.nonzero(part_mask)
    margin = int(max(30, CROP_MARGIN * max(xs.max() - xs.min(), ys.max() - ys.min())))
    left, top = max(0, xs.min() - margin), max(0, ys.min() - margin)
    right, bottom = min(image.size[0], xs.max() + margin + 1), min(image.size[1], ys.max() + margin + 1)
    detections = sam.segment(image.crop((left, top, right, bottom)), prompt, tag="crop_")
    local_reference = part_mask[top:bottom, left:right]
    scored = [(mask_iou(d.mask, local_reference), d) for d in detections]
    if not scored or max(scored, key=lambda s: s[0])[0] < 0.5:
        return None
    best = max(scored, key=lambda s: s[0])[1]
    full = np.zeros(part_mask.shape, dtype=bool)
    full[top:bottom, left:right] = best.mask
    return full


# ---------- step 2 ----------
def find_masks(out, image, sam):
    suggestions_path = out / "2_prompt_suggestions.json"
    if suggestions_path.exists():
        suggestions = json.loads(suggestions_path.read_text(encoding="utf-8"))
    else:
        prompts, content = suggest_part_prompts(out / "1_scene.png")
        suggestions = {"prompts": prompts, "answer": content}
        save_json(suggestions_path, suggestions)
    part_prompts = suggestions["prompts"] or FALLBACK_PART_PROMPTS

    attempts, card = [], None
    for prompt in CARD_PROMPTS:
        detections = sam.segment(image, prompt)
        found = [d for d in detections if card_aspect_ok(d.mask)]
        attempts.append({"object": "card", "prompt": prompt,
                         "confidences": [round(d.confidence or 0, 3) for d in detections]})
        if found:
            card = max(found, key=lambda d: d.confidence or 0)
            break
    if card is None:
        raise RuntimeError("SAM found no card")

    def try_part_prompts(prompts, source):
        found = []
        for prompt in prompts:
            detections = [d for d in sam.segment(image, prompt) if mask_iou(d.mask, card.mask) < 0.3]
            attempts.append({"object": "part", "prompt": prompt, "source": source,
                             "confidences": [round(d.confidence or 0, 3) for d in detections]})
            found += [(d.confidence or 0, prompt, d) for d in detections]
        return found

    options = try_part_prompts(part_prompts, "suggested")
    if not options:  # the suggestions can misread the part (a gray plate was called a "banknote")
        options = try_part_prompts([p for p in FALLBACK_PART_PROMPTS if p not in part_prompts], "fallback")
    if not options:
        save_json(out / "2_sam_attempts.json", attempts)
        raise RuntimeError(f"SAM found no part with prompts {part_prompts}")
    confidence, part_prompt, part = max(options, key=lambda o: o[0])

    crop_mask = segment_crop(sam, image, part.mask, part_prompt)
    save_json(out / "2_sam_attempts.json", {"suggested_prompts": suggestions["prompts"], "attempts": attempts,
                                             "chosen_part_prompt": part_prompt, "crop_found": crop_mask is not None})
    cv2.imwrite(str(out / "2_sam_overlay.jpg"), draw_overlay(image, [
        ("card", card.mask, card.box, None, (255, 140, 0)),
        (part_prompt, part.mask, part.box, None, (0, 0, 255)),
    ]))
    print(f"[2] suggested prompts: {suggestions['prompts'] or '(none, using fallback)'}")
    for attempt in attempts:
        print(f"    SAM {attempt['object']:4s} '{attempt['prompt']}'"
              f"{' (fallback)' if attempt.get('source') == 'fallback' else ''}: {attempt['confidences']}")
    print(f"    part: '{part_prompt}' (confidence {confidence:.3f}); crop re-segmentation "
          f"{'found the part' if crop_mask is not None else 'FAILED'}")
    return card, part, crop_mask


# ---------- step 3 ----------
def measure(out, image, card, part, crop_mask, truth, true_masks):
    corners = card_corners(largest_contour(card.mask))
    homography, _ = card_homography(corners)
    masks = {"sam_full": part.mask}
    if crop_mask is not None:
        masks["sam_crop"] = crop_mask
    masks["color"], _ = refine_holes(image, part.mask)
    tables = {name: measure_part(mask, homography) for name, mask in masks.items()}
    comparisons = {name: compare_to_truth(table, truth) for name, table in tables.items()}

    chosen = "sam_crop" if "sam_crop" in tables and holes_look_right(tables["sam_crop"]) else "color"
    table = tables[chosen]
    save_json(out / "3_measurements.json", {
        "chosen_method": chosen, "table": table, "card_edge_differences": edge_differences(corners),
        "tables": tables, "errors_vs_truth": comparisons,
        "mask_iou_vs_truth": {name: round(mask_iou(mask, true_masks["part"]), 4) for name, mask in masks.items()},
    })

    print(f"[3] hole methods vs truth ({len(truth['holes'])} holes, diameters "
          f"{[h['diameter_mm'] for h in truth['holes']]} mm):")
    for name, comparison in comparisons.items():
        found = [h for h in comparison["holes"] if h["center_error_mm"] is not None]
        d_err = max((abs(h["diameter_error_mm"]) for h in found), default=float("nan"))
        c_err = max((h["center_error_mm"] for h in found), default=float("nan"))
        print(f"    {name:9s} holes {tables[name]['hole_count']:2d}  max diameter error {d_err:5.2f} mm  "
              f"max center error {c_err:5.2f} mm  mask IoU {mask_iou(masks[name], true_masks['part']):.4f}"
              f"{'  <- used' if name == chosen else ''}")
    print(f"    outline {table['outline']['length_mm']} x {table['outline']['width_mm']} mm "
          f"(true {truth['length']} x {truth['width']}), {table['outline']['vertex_count']} corners "
          f"(true {truth['outline_vertices']})")

    center = np.array(table["center_on_table_mm"])
    half = table["outline"]["length_mm"] / 2 + 8
    view, _ = rectify_image(masks[chosen].astype(np.uint8) * 255, homography, (*(center - half), *(center + half)),
                            MM_PER_PIXEL)
    reference = view >= 128
    cv2.imwrite(str(out / "3_part_mask_topdown.png"), reference.astype(np.uint8) * 255)
    return table, reference, comparisons


# ---------- step 4 ----------
def make_candidates(out, table, count):
    folder = out / "candidates"
    folder.mkdir(exist_ok=True)
    cached = sorted(folder.glob("cand_*_response.json"), key=lambda p: int(p.stem.split("_")[1]))
    if len(cached) >= count:
        responses = [json.loads(p.read_text(encoding="utf-8")) for p in cached[:count]]
        print(f"[4] using {count} cached candidates")
    else:
        prompt, responses = generate_candidates(table, out / "3_part_mask_topdown.png", count)
        (out / "4_prompt.txt").write_text(prompt, encoding="utf-8")
        for i, response in enumerate(responses, 1):
            save_json(folder / f"cand_{i}_response.json", response)
    entries = []
    for i, response in enumerate(responses, 1):
        path = folder / f"cand_{i}.py"
        if "error" in response:
            entries.append((path, f"request failed: {response['error']}"))
            continue
        choice = response["choices"][0]
        code = extract_python_block(choice["message"]["content"])
        if code is None:
            entries.append((path, f"no python code block (finish={choice['finish_reason']}, "
                                  f"{(response.get('usage') or {}).get('completion_tokens')} output tokens)"))
            continue
        path.write_text(code, encoding="utf-8")
        entries.append((path, None))
    return entries


# ---------- step 5 ----------
def validate(out, entries, reference, truth, truth_workplane):
    ceiling = aligned_iou(reference, MM_PER_PIXEL, render_top_silhouette(truth_workplane, MM_PER_PIXEL) > 0,
                          MM_PER_PIXEL).iou
    scale = np.diag([MM_PER_PIXEL, MM_PER_PIXEL, 1.0])
    rows = []
    for i, (path, error) in enumerate(entries, 1):
        row = {"candidate": i, "file": str(path)}
        mask = None
        if error is None:
            mask, error = run_candidate(path, MM_PER_PIXEL)
        if error:
            row["error"] = error
            rows.append(row)
            continue
        alignment = aligned_iou(reference, MM_PER_PIXEL, mask, MM_PER_PIXEL)
        table = measure_part(mask, scale)
        ok, issues = check_topology(table, truth)
        row.update({"iou": round(alignment.iou, 4), "topology_ok": ok, "topology_issues": issues,
                    "outline_mm": [table["outline"]["length_mm"], table["outline"]["width_mm"]],
                    "corners": table["outline"]["vertex_count"], "hole_count": table["hole_count"],
                    "hole_diameters_mm": sorted(h["diameter_mm"] for h in table["holes"]),
                    # |u|, |v|, diameter rounded to 1 mm: ignores mirroring, separates real layout changes
                    "hole_layout": sorted((round(abs(h["center_from_part_center_mm"][0])),
                                           round(abs(h["center_from_part_center_mm"][1])),
                                           round(h["diameter_mm"])) for h in table["holes"])})
        row["_alignment"] = alignment
        rows.append(row)

    compiled = [r for r in rows if "iou" in r]
    correct = [r for r in compiled if r["topology_ok"]]
    shapes = {(r["corners"], tuple(map(tuple, r["hole_layout"])), tuple(round(x) for x in r["outline_mm"]))
              for r in compiled}
    print(f"[5] {len(compiled)}/{len(rows)} compiled, {len(correct)}/{len(rows)} correct topology, "
          f"{len(shapes)} distinct shape(s); IoU ceiling (true part vs reference) {ceiling:.4f}")
    for r in rows:
        if "error" in r:
            print(f"    cand {r['candidate']:2d}  FAILED  {r['error'].strip().splitlines()[-1]}")
        else:
            status = "ok" if r["topology_ok"] else "WRONG: " + "; ".join(r["topology_issues"])
            print(f"    cand {r['candidate']:2d}  IoU {r['iou']:.4f}  corners {r['corners']}  holes "
                  f"{r['hole_diameters_mm']}  {status}")

    best = max(compiled, key=lambda r: r["iou"]) if compiled else None
    if best:
        a = best["_alignment"]
        xor = np.zeros((*a.reference.shape, 3), dtype=np.uint8)
        xor[a.reference & a.candidate] = (255, 255, 255)
        xor[a.reference & ~a.candidate] = (0, 0, 255)  # red: in the photo, missing in the model
        xor[~a.reference & a.candidate] = (255, 128, 0)  # blue: in the model, not in the photo
        cv2.imwrite(str(out / "5_best_xor.png"), xor)
        print(f"    best: candidate {best['candidate']} (IoU {best['iou']:.4f}, "
              f"topology {'ok' if best['topology_ok'] else 'wrong'})")
    summary = {"iou_ceiling": round(ceiling, 4), "compiled": len(compiled), "correct_topology": len(correct),
               "distinct_shapes": len(shapes), "best_candidate": best["candidate"] if best else None,
               "candidates": [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]}
    save_json(out / "5_summary.json", summary)
    return summary


def run_scene(name, photo_rgb, true_masks, truth, truth_workplane, out_dir, candidate_count):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"\n######## scene {name} ########")
    cv2.imwrite(str(out / "1_scene.png"), cv2.cvtColor(photo_rgb, cv2.COLOR_RGB2BGR))
    save_json(out / "1_truth.json", truth)
    image = load_photo(out / "1_scene.png")
    sam = SamCache(out / "sam")
    card, part, crop_mask = find_masks(out, image, sam)
    table, reference, comparisons = measure(out, image, card, part, crop_mask, truth, true_masks)
    result = {"scene": name, "hole_methods": comparisons}
    if candidate_count:
        entries = make_candidates(out, table, candidate_count)
        result["candidates"] = validate(out, entries, reference, truth, truth_workplane)
    return result
