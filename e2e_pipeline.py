"""End-to-end pipeline for one scene: photo -> SAM masks -> measurements -> candidate
CadQuery code -> compile -> silhouette -> IoU, topology and design-intent checks.

Steps and their outputs (in the scene's output folder):
  1  scene image and ground truth
  2  the part is selected by a click (SAM point prompt); if that fails, by name (Muse Spark
     Open suggests SAM prompts, fixed fallbacks after that); the part is cropped (with a
     margin) and segmented again to see small holes in more detail
  3  measurement tables from three hole methods (full SAM mask, cropped SAM mask, color),
     each compared with the truth; color is used unless its holes look wrong, then the cropped mask
  4  candidate programs from Muse Spark Open, plus a baseline program without a language model
  5  compile, render, IoU, topology check, variety; the winner (correct topology first, then
     IoU, then fewer parameters) and the baseline get the design-intent test
SAM and Muse Spark Open answers are cached in the folder; delete them to ask again.
"""
import json
from pathlib import Path

import cv2
import numpy as np

from baseline_cad import baseline_code
from candidates import extract_python_block, generate_candidates
from design_intent import evaluate as evaluate_design_intent
from design_intent import parameters
from deviation_check import check_deviation
from model_view import model_view
from homography import card_corners, card_homography, edge_differences, is_tilted, largest_contour, rectify_image
from iou import aligned_iou
from measure import CARD_LONG_MM, CARD_SHORT_MM, card_scale
from overlay import draw_overlay
from part_measurements import check_topology, compare_to_truth, measure_part
from prompt_suggestions import suggest_part_prompts
from refine_holes import refine_holes
from render_silhouette import render_top_silhouette
from run_candidate import run_candidate
from sam_client import load_photo, make_client, parse_detections, point_prompt, segment

MM_PER_PIXEL = 0.1  # top-down resolution for masks, renders and IoU
SCALE = np.diag([MM_PER_PIXEL, MM_PER_PIXEL, 1.0])  # render pixels -> mm
CARD_PROMPTS = ["credit card", "card", "bank card"]
FALLBACK_PART_PROMPTS = ["metal plate", "plate", "flat metal part"]
CROP_MARGIN = 0.15  # crop margin as a share of the part's larger side
MIN_HOLE_SOLIDITY = 0.9  # area / convex hull area; fragments and bites score lower
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
    """Every hole is a clean circle, rectangle or slot of a sensible size (not a fragment)."""
    return all(h["shape"] != "polygon" and h["solidity"] >= MIN_HOLE_SOLIDITY
               and h["diameter_mm"] >= MIN_HOLE_DIAMETER_MM for h in table["holes"])


def simulated_click(part_mask):
    """The pixel deepest inside the part's material: where a user would click to pick it."""
    distance = cv2.distanceTransform(part_mask.astype(np.uint8), cv2.DIST_L2, 5)
    y, x = np.unravel_index(np.argmax(distance), distance.shape)
    return int(x), int(y)


class SamCache:
    """SAM calls with their raw answers cached as text files."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.client = None

    def segment(self, image, prompt, tag="", key=None):
        path = self.folder / f"{tag}{key or prompt.replace(' ', '_')}.txt"
        if path.exists():
            return parse_detections(path.read_text(encoding="utf-8"), image.size)
        self.client = self.client or make_client()
        detections, raw_text = segment(self.client, image, prompt)
        path.write_text(raw_text, encoding="utf-8")
        return detections


def segment_crop(sam, image, part_mask, prompt, click=None):
    """Segment the part again inside a crop around it; return a full-size mask or None.

    With a click, the crop is prompted with the same point (shifted into the crop); else by name.
    """
    ys, xs = np.nonzero(part_mask)
    margin = int(max(30, CROP_MARGIN * max(xs.max() - xs.min(), ys.max() - ys.min())))
    left, top = max(0, xs.min() - margin), max(0, ys.min() - margin)
    right, bottom = min(image.size[0], xs.max() + margin + 1), min(image.size[1], ys.max() + margin + 1)
    crop = image.crop((left, top, right, bottom))
    if click is not None:
        detections = sam.segment(crop, point_prompt(crop.size, click[0] - left, click[1] - top), tag="crop_",
                                 key="point")
    else:
        detections = sam.segment(crop, prompt, tag="crop_")
    local_reference = part_mask[top:bottom, left:right]
    scored = [(mask_iou(d.mask, local_reference), d) for d in detections]
    if not scored or max(scored, key=lambda s: s[0])[0] < 0.5:
        return None
    best = max(scored, key=lambda s: s[0])[1]
    full = np.zeros(part_mask.shape, dtype=bool)
    full[top:bottom, left:right] = best.mask
    return full


# ---------- step 2 ----------
def find_masks(out, image, sam, click, photo_path, suggest=True):
    """Card and part masks. suggest=False never sends the photo to Muse Spark Open for prompt names."""
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

    def try_prompts(prompts, source):
        found = []
        for prompt, key in prompts:
            detections = [d for d in sam.segment(image, prompt, key=key) if mask_iou(d.mask, card.mask) < 0.3]
            if source == "click":  # the selected object must lie under the click
                detections = [d for d in detections if d.mask[click[1], click[0]]]
            attempts.append({"object": "part", "prompt": prompt, "source": source,
                             "confidences": [round(d.confidence or 0, 3) for d in detections]})
            found += [(d.confidence or 0, prompt, source, d) for d in detections]
        return found

    options = try_prompts([(point_prompt(image.size, *click), "point")], "click") if click else []
    suggestions = None
    if not options and suggest:  # fall back to finding the part by name
        suggestions_path = out / "2_prompt_suggestions.json"
        if suggestions_path.exists():
            suggestions = json.loads(suggestions_path.read_text(encoding="utf-8"))
        else:
            prompts, content = suggest_part_prompts(photo_path)
            suggestions = {"prompts": prompts, "answer": content}
            save_json(suggestions_path, suggestions)
        options = try_prompts([(p, None) for p in suggestions["prompts"]], "suggested")
    if not options:  # the suggestions can misread the part (a gray plate was called a "banknote")
        tried = suggestions["prompts"] if suggestions else []
        options = try_prompts([(p, None) for p in FALLBACK_PART_PROMPTS if p not in tried], "fallback")
    if not options:
        save_json(out / "2_sam_attempts.json", attempts)
        raise RuntimeError("SAM found no part")
    confidence, part_prompt, source, part = max(options, key=lambda o: o[0])

    crop_mask = segment_crop(sam, image, part.mask, part_prompt, click if source == "click" else None)
    save_json(out / "2_sam_attempts.json", {"click": click, "attempts": attempts, "chosen_source": source,
                                             "chosen_prompt": part_prompt, "crop_found": crop_mask is not None})
    cv2.imwrite(str(out / "2_sam_overlay.jpg"), draw_overlay(image, [
        ("card", card.mask, card.box, None, (255, 140, 0)),
        ("part", part.mask, part.box, None, (0, 0, 255)),
    ]))
    for attempt in attempts:
        label = attempt["prompt"] if attempt.get("source") != "click" else f"point {click}"
        print(f"[2] SAM {attempt['object']:4s} {label!r} ({attempt.get('source', 'name')}): {attempt['confidences']}")
    print(f"    part chosen by {source} (confidence {confidence:.3f}); crop re-segmentation "
          f"{'found the part' if crop_mask is not None else 'FAILED'}")
    return card, part, crop_mask, source


# ---------- step 3 ----------
def describe_hole(hole):
    u, v = hole["center_from_part_center_mm"]
    if hole["shape"] == "circle":
        size = f"diameter {hole['diameter_mm']:.2f}"
    elif hole["shape"] in ("rectangle", "slot", "ellipse"):
        size = f"{hole['length_mm']:.2f} x {hole['width_mm']:.2f}, angle {hole['angle_deg']}"
    else:
        size = (f"{len(hole['polygon_mm'])} corners, bounding {hole['length_mm']:.2f} x {hole['width_mm']:.2f}, "
                f"equal-area diameter {hole['diameter_mm']:.2f}")
    return f"{hole['shape']:9s} {size} mm at [{u:.1f}, {v:.1f}] (match {hole['shape_match']}, solidity {hole['solidity']})"


def pixel_to_mm_scales(card_mask):
    """Both pixel-to-mm mappings and which one the tilt rule picks.

    Temporary rule: homography only when the card's opposite edges differ by more than 2% (tilted
    camera); otherwise the simple mean card scale. On real photos with a small card and the part 1-2
    card lengths away, the homography extrapolated corner errors (+4-10%); both results are kept.
    """
    corners = card_corners(largest_contour(card_mask))
    differences = edge_differences(corners)
    homography, _ = card_homography(corners)
    mm_per_pixel = card_scale(card_mask).mm_per_pixel
    simple = np.diag([mm_per_pixel, mm_per_pixel, 1.0])
    chosen = "homography" if is_tilted(differences) else "simple"
    return {"homography": homography, "simple": simple}, chosen, differences


def measure(out, image, card, part, crop_mask, truth=None, true_masks=None):
    """Measurement tables from each hole method; truth and true masks are optional (real photos)."""
    scales, scale_used, differences = pixel_to_mm_scales(card.mask)
    homography = scales[scale_used]
    masks = {"sam_full": part.mask}
    if crop_mask is not None:
        masks["sam_crop"] = crop_mask
    masks["color"], _ = refine_holes(image, part.mask)
    tables = {name: measure_part(mask, homography) for name, mask in masks.items()}
    other_scale = "simple" if scale_used == "homography" else "homography"
    other_tables = {name: measure_part(mask, scales[other_scale]) for name, mask in masks.items()}
    print(f"[3] card edges L-R/T-B {[round(float(d) * 100, 2) for d in differences]} % -> using {scale_used} scale")
    for name in masks:
        print(f"    {name:9s} outline {scale_used}: {tables[name]['outline']['length_mm']} x "
              f"{tables[name]['outline']['width_mm']} mm, {other_scale}: {other_tables[name]['outline']['length_mm']}"
              f" x {other_tables[name]['outline']['width_mm']} mm")
    if truth is None:
        for name, table in tables.items():
            print(f"    {name:9s} outline {table['outline']['length_mm']} x {table['outline']['width_mm']} mm, "
                  f"{table['outline']['vertex_count']} corners, {table['hole_count']} holes"
                  f"{'' if holes_look_right(table) else '  (hole check FAILS)'}")
            for hole in table["holes"]:
                print(f"        {describe_hole(hole)}")
        comparisons = {}
    else:
        comparisons = {name: compare_to_truth(table, truth) for name, table in tables.items()}

    # Color first: it was the most accurate in every synthetic scene. The cropped SAM mask is the
    # fallback; its holes came out about 3% too large there.
    if holes_look_right(tables["color"]):
        chosen = "color"
    elif "sam_crop" in tables and holes_look_right(tables["sam_crop"]):
        chosen = "sam_crop"
    else:
        chosen = "color"
    table = tables[chosen]
    save_json(out / "3_measurements.json", {
        "chosen_method": chosen, "scale_used": scale_used, "table": table, "card_edge_differences": differences,
        "tables": tables, f"tables_with_{other_scale}_scale": other_tables, "errors_vs_truth": comparisons,
        f"errors_vs_truth_with_{other_scale}_scale": {name: compare_to_truth(t, truth) for name, t in
                                                     other_tables.items()} if truth else {},
        "mask_iou_vs_truth": {name: round(mask_iou(mask, true_masks["part"]), 4) for name, mask in masks.items()}
        if true_masks else None,
    })
    for name, mask in masks.items():  # each method's part mask, for visual checks
        cv2.imwrite(str(out / f"3_mask_{name}.png"), mask.astype(np.uint8) * 255)

    if truth is None:
        print(f"    used: {chosen}")
    else:
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
    return table, reference, comparisons, chosen


# ---------- step 4 ----------
def make_candidates(out, folder_name, table, count):
    folder = out / folder_name
    folder.mkdir(exist_ok=True)
    cached = sorted(folder.glob("cand_*_response.json"), key=lambda p: int(p.stem.split("_")[1]))
    if len(cached) >= count:
        responses = [json.loads(p.read_text(encoding="utf-8")) for p in cached[:count]]
        print(f"[4] using {count} cached candidates from {folder_name}/")
    else:
        prompt, responses = generate_candidates(model_view(table), out / "3_part_mask_topdown.png", count)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        for i, response in enumerate(responses, 1):
            save_json(folder / f"cand_{i}_response.json", response)
    tokens = [(r.get("usage") or {}).get("completion_tokens") for r in responses if "error" not in r]
    seconds = [r["elapsed_s"] for r in responses if "elapsed_s" in r]
    if tokens:
        print(f"[4] output tokens: mean {np.mean(tokens):.0f}, max {max(tokens)}"
              + (f"; request time: mean {np.mean(seconds):.0f} s, batch {responses[0]['batch_elapsed_s']:.0f} s"
                 if seconds else ""))
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
    baseline_path = folder / "baseline.py"
    baseline_path.write_text(baseline_code(table), encoding="utf-8")
    return entries, baseline_path


# ---------- step 5 ----------
def check_program(path, reference, truth=None, measured_table=None):
    """Compile and score one program; returns a result row (without 'candidate').

    Without a truth (real photos) topology_ok is None. With the measured table, the deviation check
    says whether the program's dimensions stay within the allowed distance of the measurements.
    """
    mask, error = run_candidate(path, MM_PER_PIXEL)
    if error:
        return {"file": str(path), "error": error}
    alignment = aligned_iou(reference, MM_PER_PIXEL, mask, MM_PER_PIXEL)
    table = measure_part(mask, SCALE)
    ok, issues = check_topology(table, truth) if truth else (None, [])
    deviation_ok, deviation_rows = check_deviation(model_view(measured_table), table) if measured_table \
        else (True, [])
    return {"file": str(path), "iou": round(alignment.iou, 4), "topology_ok": ok, "topology_issues": issues,
            "deviation_ok": deviation_ok, "deviation": deviation_rows,
            "outline_mm": [table["outline"]["length_mm"], table["outline"]["width_mm"]],
            "corners": table["outline"]["vertex_count"], "hole_count": table["hole_count"],
            "hole_diameters_mm": sorted(h["diameter_mm"] for h in table["holes"]),
            # |u|, |v|, diameter rounded to 1 mm: ignores mirroring, separates real layout changes
            "hole_layout": sorted((round(abs(h["center_from_part_center_mm"][0])),
                                   round(abs(h["center_from_part_center_mm"][1])),
                                   round(h["diameter_mm"])) for h in table["holes"]),
            "parameter_count": len(parameters(Path(path).read_text(encoding="utf-8"))),
            "_alignment": alignment}


def validate(out, folder_name, entries, baseline_path, reference, truth=None, truth_workplane=None,
             measured_table=None):
    """Score all candidates and the baseline. Truth and the true part are optional (real photos).

    Candidates whose dimensions stray too far from measured_table are rejected (deviation_check.py).
    """
    ceiling = aligned_iou(reference, MM_PER_PIXEL, render_top_silhouette(truth_workplane, MM_PER_PIXEL) > 0,
                          MM_PER_PIXEL).iou if truth_workplane is not None else float("nan")
    rows = []
    for i, (path, error) in enumerate(entries, 1):
        row = {"file": str(path), "error": error} if error else check_program(path, reference, truth,
                                                                               measured_table)
        rows.append({"candidate": i, **row})

    compiled = [r for r in rows if "iou" in r]
    correct = [r for r in compiled if r["topology_ok"]]
    shapes = {(r["corners"], tuple(map(tuple, r["hole_layout"])), tuple(round(x) for x in r["outline_mm"]))
              for r in compiled}
    topology = f"{len(correct)}/{len(rows)}" if truth else "n/a (no ground truth)"
    print(f"[5] {len(compiled)}/{len(rows)} compiled, correct topology {topology}, "
          f"{len(shapes)} distinct shape(s); IoU ceiling (true part vs reference) {ceiling:.4f}")
    for r in rows:
        if "error" in r:
            print(f"    cand {r['candidate']:2d}  FAILED  {r['error'].strip().splitlines()[-1]}")
        else:
            status = {True: "ok", None: ""}.get(r["topology_ok"], "WRONG: " + "; ".join(r["topology_issues"]))
            if not r["deviation_ok"]:
                worst = [d["dimension"] for d in r["deviation"] if not d["ok"]]
                status += f"  REJECTED, too far from the measurements: {', '.join(worst)}"
            print(f"    cand {r['candidate']:2d}  IoU {r['iou']:.4f}  params {r['parameter_count']:2d}  "
                  f"corners {r['corners']}  holes {r['hole_diameters_mm']}  {status}")

    # Winner among candidates within the deviation limits: correct topology first (when known),
    # then IoU, then fewer parameters.
    eligible = [r for r in compiled if r["deviation_ok"]]
    best = max(eligible, key=lambda r: (r["topology_ok"] is not False, round(r["iou"], 3), -r["parameter_count"])) \
        if eligible else None
    print(f"    {len(eligible)}/{len(compiled)} compiled candidates within the deviation limits")
    baseline = check_program(baseline_path, reference, truth, measured_table)
    if best and best["deviation"]:
        print(f"    winner {Path(best['file']).name}: measured vs chosen")
        for d in best["deviation"]:
            print(f"      {d['dimension']:18s} measured {str(d['measured_mm']):>16s}  chosen {str(d['candidate_mm']):>16s}"
                  f"  deviation {str(d['deviation_mm']):>6s}  limit {d['limit_mm']:>5}  {'ok' if d['ok'] else 'OVER'}")
    if best:
        a = best["_alignment"]
        xor = np.zeros((*a.reference.shape, 3), dtype=np.uint8)
        xor[a.reference & a.candidate] = (255, 255, 255)
        xor[a.reference & ~a.candidate] = (0, 0, 255)  # red: in the photo, missing in the model
        xor[~a.reference & a.candidate] = (255, 128, 0)  # blue: in the model, not in the photo
        cv2.imwrite(str(out / f"5_best_xor_{folder_name}.png"), xor)
    for label, row in [("winner", best), ("baseline", baseline)]:
        if not row or "iou" not in row:
            continue
        # The design-intent test needs the true part (repeated holes, symmetry); without it only count parameters.
        intent = evaluate_design_intent(row["file"], truth) if truth else {"parameter_count": row["parameter_count"]}
        row["design_intent"] = intent
        print(f"    {label:8s} {Path(row['file']).name:12s} IoU {row['iou']:.4f}  "
              f"topology {({True: 'ok', None: 'n/a'}).get(row['topology_ok'], 'WRONG')}  "
              f"params {intent['parameter_count']:2d}  holes linked {intent.get('hole_diameter_linked')}  "
              f"length param {intent.get('length_parameter')}  "
              f"symmetric {intent.get('symmetric_after_length_change')}  edge margin {intent.get('edge_margin_kept')}")

    def clean(row):
        return {k: v for k, v in row.items() if not k.startswith("_")} if row else None

    summary = {"iou_ceiling": round(ceiling, 4), "compiled": len(compiled), "within_deviation": len(eligible),
               "correct_topology": len(correct),
               "candidate_count": len(rows), "distinct_shapes": len(shapes), "winner": clean(best),
               "baseline": clean(baseline), "candidates": [clean(r) for r in rows]}
    save_json(out / f"5_summary_{folder_name}.json", summary)
    return summary


def run_scene(name, photo_rgb, true_masks, truth, truth_workplane, out_dir, candidate_count,
              candidates_folder="candidates_arcs", click=True):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"\n######## scene {name} ########")
    cv2.imwrite(str(out / "1_scene.png"), cv2.cvtColor(photo_rgb, cv2.COLOR_RGB2BGR))
    save_json(out / "1_truth.json", truth)
    image = load_photo(out / "1_scene.png")
    sam = SamCache(out / "sam")
    click_point = simulated_click(true_masks["part"]) if click else None
    card, part, crop_mask, source = find_masks(out, image, sam, click_point, out / "1_scene.png")
    table, reference, comparisons, hole_method = measure(out, image, card, part, crop_mask, truth, true_masks)
    result = {"scene": name, "part_found_by": source, "hole_method": hole_method, "hole_methods": comparisons}
    if candidate_count:
        entries, baseline_path = make_candidates(out, candidates_folder, table, candidate_count)
        result["candidates"] = validate(out, candidates_folder, entries, baseline_path, reference, truth,
                                        truth_workplane, table)
    return result


def run_photo(name, photo_path, click, out_dir, candidate_count, candidates_folder="candidates_arcs",
              suggest=True):
    """The same pipeline on a real photo: no ground truth, the part is picked by `click` (x, y in pixels).

    suggest=False keeps the photo away from Muse Spark Open (only SAM sees it).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"\n######## photo {name} ########")
    image = load_photo(photo_path)
    sam = SamCache(out / "sam")
    card, part, crop_mask, source = find_masks(out, image, sam, click, photo_path, suggest)
    table, reference, _, hole_method = measure(out, image, card, part, crop_mask)
    result = {"photo": name, "part_found_by": source, "hole_method": hole_method, "table": table}
    if candidate_count:
        entries, baseline_path = make_candidates(out, candidates_folder, table, candidate_count)
        result["candidates"] = validate(out, candidates_folder, entries, baseline_path, reference,
                                        measured_table=table)
    return result
