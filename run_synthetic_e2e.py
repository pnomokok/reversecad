"""End-to-end skeleton on a synthetic scene: photo -> SAM masks -> measurements ->
candidate CadQuery code -> compile -> silhouette -> IoU -> best candidate.

Every step writes its output to outputs/e2e/. SAM and Muse Spark Open answers
are cached there, so re-running only repeats the local steps; delete the cache
files (outputs/e2e/sam/, outputs/e2e/candidates/) to ask the models again.

Run: .venv\\Scripts\\python.exe run_synthetic_e2e.py
"""
import json
from pathlib import Path

import cv2
import numpy as np

from candidates import extract_python_block, generate_candidates
from homography import card_corners, card_homography, edge_differences, is_tilted, largest_contour, rectify_image
from iou import aligned_iou
from measure import CARD_LONG_MM, CARD_SHORT_MM
from overlay import draw_overlay
from part_measurements import compare_to_truth, measure_part
from parts.holed_plate import make_holed_plate
from refine_holes import refine_holes
from render_silhouette import render_top_silhouette
from run_candidate import run_candidate
from sam_client import load_photo, make_client, parse_detections, segment
from synthetic_scene import PLATE, make_scene

OUT = Path("outputs") / "e2e"
CANDIDATE_COUNT = 5
MM_PER_PIXEL = 0.1  # top-down resolution for masks, renders and IoU
CARD_PROMPTS = ["credit card", "card", "bank card"]
PART_PROMPTS = ["plate", "metal plate", "flat metal part", "gray rectangle"]


def save_json(name, data):
    # numpy numbers (float32, int64) are not JSON types; .item() turns them into plain Python numbers.
    (OUT / name).write_text(json.dumps(data, indent=2, default=lambda o: o.item()), encoding="utf-8")


def mask_iou(a, b):
    union = np.count_nonzero(a | b)
    return np.count_nonzero(a & b) / union if union else 0.0


def card_aspect_ok(mask):
    (_, (w, h), _) = cv2.minAreaRect(largest_contour(mask).astype(np.float32))
    aspect = max(w, h) / min(w, h)
    return abs(aspect - CARD_LONG_MM / CARD_SHORT_MM) < 0.15


# ---------- step 1 ----------
def step1_scene():
    photo, true_masks, truth = make_scene()
    cv2.imwrite(str(OUT / "1_scene.png"), cv2.cvtColor(photo, cv2.COLOR_RGB2BGR))
    save_json("1_truth.json", truth)
    print(f"[1] scene saved: {OUT / '1_scene.png'}  (truth in 1_truth.json)")
    return true_masks, truth


# ---------- step 2 ----------
def step2_sam(image):
    sam_dir = OUT / "sam"
    sam_dir.mkdir(exist_ok=True)
    client = []
    attempts = []

    def try_prompt(prompt):
        path = sam_dir / f"{prompt.replace(' ', '_')}.txt"
        if path.exists():
            detections = parse_detections(path.read_text(encoding="utf-8"), image.size)
        else:
            if not client:
                client.append(make_client())
            detections, raw_text = segment(client[0], image, prompt)
            path.write_text(raw_text, encoding="utf-8")
        attempts.append({"prompt": prompt, "detections": len(detections),
                         "confidences": [round(d.confidence or 0, 3) for d in detections]})
        return detections

    card = None
    for prompt in CARD_PROMPTS:
        found = [d for d in try_prompt(prompt) if card_aspect_ok(d.mask)]
        if found:
            card = max(found, key=lambda d: d.confidence or 0)
            attempts[-1]["used"] = True
            break
    if card is None:
        save_json("2_sam_attempts.json", attempts)
        raise RuntimeError("SAM found no card with any prompt; see 2_sam_attempts.json")

    part = None
    for prompt in PART_PROMPTS:
        found = [d for d in try_prompt(prompt) if mask_iou(d.mask, card.mask) < 0.3]  # not the card again
        if found:
            part = max(found, key=lambda d: d.confidence or 0)
            attempts[-1]["used"] = True
            break
    save_json("2_sam_attempts.json", attempts)
    if part is None:
        raise RuntimeError("SAM found no part with any prompt; see 2_sam_attempts.json")

    cv2.imwrite(str(OUT / "2_sam_overlay.jpg"), draw_overlay(image, [
        ("card", card.mask, card.box, None, (255, 140, 0)),
        ("part", part.mask, part.box, None, (0, 0, 255)),
    ]))
    for attempt in attempts:
        print(f"[2] SAM '{attempt['prompt']}': {attempt['detections']} detection(s) "
              f"{attempt['confidences']}{'  <- used' if attempt.get('used') else ''}")
    return card, part


# ---------- step 3 ----------
def step3_measure(image, card, part, true_masks, truth):
    corners = card_corners(largest_contour(card.mask))
    tilt = edge_differences(corners)
    homography, _ = card_homography(corners)
    sam_only = measure_part(part.mask, homography)
    part_mask, _ = refine_holes(image, part.mask)
    table = measure_part(part_mask, homography)
    errors = compare_to_truth(table, truth["plate"])
    mask_vs_truth = {name: round(float(mask_iou(mask, true_masks[truth_name])), 4)
                     for name, truth_name, mask in [("card", "card", card.mask), ("plate_sam", "plate", part.mask),
                                                    ("plate_refined", "plate", part_mask)]}
    save_json("3_measurements.json", {"table": table, "errors_vs_truth": errors, "sam_only_table": sam_only,
                                      "card_edge_differences": tilt, "mask_iou_vs_truth": mask_vs_truth})
    print(f"[3] SAM mask alone: {sam_only['hole_count']} holes, diameters "
          f"{[h['diameter_mm'] for h in sam_only['holes']]}; after hole refinement: {table['hole_count']} holes")

    # Top-down part mask: the reference for IoU and the image the model sees.
    center = np.array(table["center_on_table_mm"])
    half = (table["outline"]["length_mm"] / 2 + 8)
    region = (*(center - half), *(center + half))
    view, _ = rectify_image(part_mask.astype(np.uint8) * 255, homography, region, MM_PER_PIXEL)
    reference = view >= 128
    cv2.imwrite(str(OUT / "3_part_mask_topdown.png"), reference.astype(np.uint8) * 255)

    print(f"[3] card edges L-R {tilt[0]:+.2%}, T-B {tilt[1]:+.2%}"
          f"{'  (tilt warning)' if is_tilted(tilt) else ''}; mask IoU vs truth {mask_vs_truth}")
    o = table["outline"]
    print(f"    outline {o['length_mm']} x {o['width_mm']} mm (true {PLATE['length']} x {PLATE['width']}), "
          f"error {errors['length_mm']:+.2f} / {errors['width_mm']:+.2f} mm")
    print(f"    holes {table['hole_count']} (true 4)")
    for hole, center_error in zip(table["holes"], errors["hole_center_mm"]):
        print(f"      center {hole['center_from_part_center_mm']} mm, diameter {hole['diameter_mm']} mm "
              f"(true 6.0), center error {center_error:.2f} mm")
    return table, reference


# ---------- step 4 ----------
def step4_candidates(table):
    cand_dir = OUT / "candidates"
    cand_dir.mkdir(exist_ok=True)
    cached = sorted(cand_dir.glob("cand_*_response.json"))
    if len(cached) >= CANDIDATE_COUNT:
        responses = [json.loads(p.read_text(encoding="utf-8")) for p in cached[:CANDIDATE_COUNT]]
        print(f"[4] using {CANDIDATE_COUNT} cached candidates")
    else:
        prompt, responses = generate_candidates(table, OUT / "3_part_mask_topdown.png", CANDIDATE_COUNT)
        (OUT / "4_prompt.txt").write_text(prompt, encoding="utf-8")
        for i, response in enumerate(responses, 1):
            (cand_dir / f"cand_{i}_response.json").write_text(json.dumps(response, indent=2), encoding="utf-8")

    code_paths = []
    for i, response in enumerate(responses, 1):
        code_path = cand_dir / f"cand_{i}.py"
        if "error" in response:
            print(f"[4] candidate {i}: request failed: {response['error']}")
            code_paths.append((code_path, f"request failed: {response['error']}", None))
            continue
        choice = response["choices"][0]
        code = extract_python_block(choice["message"]["content"])
        usage = response.get("usage") or {}
        tokens = f"{usage.get('completion_tokens')} output tokens, finish={choice['finish_reason']}"
        if code is None:
            print(f"[4] candidate {i}: no ```python block ({tokens})")
            code_paths.append((code_path, "no python code block in the answer", tokens))
            continue
        code_path.write_text(code, encoding="utf-8")
        print(f"[4] candidate {i}: {len(code.splitlines())} lines of code ({tokens})")
        code_paths.append((code_path, None, tokens))
    return code_paths


# ---------- step 5 ----------
def step5_validate(code_paths, reference):
    results = []
    oracle = aligned_iou(reference, MM_PER_PIXEL, render_top_silhouette(make_holed_plate(**PLATE), MM_PER_PIXEL) > 0,
                         MM_PER_PIXEL).iou
    for i, (code_path, earlier_error, _) in enumerate(code_paths, 1):
        row = {"candidate": i, "file": str(code_path)}
        mask, error = (None, earlier_error) if earlier_error else run_candidate(code_path, MM_PER_PIXEL)
        if error:
            row["error"] = error
            results.append(row)
            continue
        alignment = aligned_iou(reference, MM_PER_PIXEL, mask, MM_PER_PIXEL)
        candidate_table = measure_part(mask, np.diag([MM_PER_PIXEL, MM_PER_PIXEL, 1.0]))
        row.update({
            "iou": round(alignment.iou, 4),
            "rotation_deg": alignment.rotation_deg,
            "mirrored": alignment.mirrored,
            "outline_mm": [candidate_table["outline"]["length_mm"], candidate_table["outline"]["width_mm"]],
            "hole_count": candidate_table["hole_count"],
            "hole_diameters_mm": [h["diameter_mm"] for h in candidate_table["holes"]],
        })
        row["_alignment"] = alignment
        results.append(row)

    print(f"\n[5] reference IoU ceiling: true CadQuery plate vs the SAM mask = {oracle:.4f}")
    print(f"    {'cand':4s} {'IoU':>7s} {'outline mm':>15s} {'holes':>5s}  hole diameters / error")
    for row in results:
        if "error" in row:
            first_line = row["error"].splitlines()[-1] if row["error"] else ""
            print(f"    {row['candidate']:<4d} {'FAILED':>7s}  {first_line}")
        else:
            outline = f"{row['outline_mm'][0]:.2f} x {row['outline_mm'][1]:.2f}"
            print(f"    {row['candidate']:<4d} {row['iou']:7.4f} {outline:>15s} {row['hole_count']:5d}  "
                  f"{row['hole_diameters_mm']}")

    passed = [row for row in results if "iou" in row]
    best = max(passed, key=lambda row: row["iou"]) if passed else None
    if best:
        alignment = best["_alignment"]
        xor = np.zeros((*alignment.reference.shape, 3), dtype=np.uint8)
        xor[alignment.reference & alignment.candidate] = (255, 255, 255)
        xor[alignment.reference & ~alignment.candidate] = (0, 0, 255)  # red: in photo, missing in model
        xor[~alignment.reference & alignment.candidate] = (255, 128, 0)  # blue: in model, not in photo
        cv2.imwrite(str(OUT / "5_best_xor.png"), xor)
        print(f"    best: candidate {best['candidate']} (IoU {best['iou']:.4f}), "
              f"XOR image 5_best_xor.png, code {best['file']}")
    summary = {"reference_iou_ceiling": round(oracle, 4),
               "best_candidate": best["candidate"] if best else None,
               "candidates": [{k: v for k, v in row.items() if not k.startswith("_")} for row in results]}
    save_json("5_summary.json", summary)
    return summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    true_masks, truth = step1_scene()
    image = load_photo(OUT / "1_scene.png")
    card, part = step2_sam(image)
    table, reference = step3_measure(image, card, part, true_masks, truth)
    code_paths = step4_candidates(table)
    step5_validate(code_paths, reference)


if __name__ == "__main__":
    main()
