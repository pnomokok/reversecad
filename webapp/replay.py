"""Read a saved pipeline run (outputs/e2e/<scene>/) and shape it for the web screens.

Replay mode: everything comes from files a run already wrote, plus SAM's cached
answers; no API is called (a missing cache file is an error, not a new request).
The measurement functions are only reused, never changed.
"""
import json
from pathlib import Path

import cv2
import numpy as np

from e2e_pipeline import CARD_PROMPTS, card_aspect_ok, pixel_to_mm_scales
from homography import card_corners, largest_contour, to_mm
from part_measurements import classify_hole
from sam_client import load_photo, parse_detections

RUNS_DIR = Path("outputs") / "e2e"


def list_runs():
    """Saved runs that reached the measurement step."""
    return sorted(p.name for p in RUNS_DIR.iterdir() if (p / "3_measurements.json").exists()) \
        if RUNS_DIR.exists() else []


def run_dir(name):
    path = (RUNS_DIR / name).resolve()
    if path.parent != RUNS_DIR.resolve() or not (path / "3_measurements.json").exists():
        raise FileNotFoundError(f"no saved run named {name!r}")
    return path


def photo_path(name):
    return run_dir(name) / "1_scene.png"


def _cached_card_mask(folder, image):
    """The card mask the run used: the first card prompt whose cached answer has a card-shaped mask."""
    for prompt in CARD_PROMPTS:
        cache = folder / "sam" / f"{prompt.replace(' ', '_')}.txt"
        if not cache.exists():
            continue
        found = [d for d in parse_detections(cache.read_text(encoding="utf-8"), image.size) if card_aspect_ok(d.mask)]
        if found:
            return max(found, key=lambda d: d.confidence or 0).mask
    raise FileNotFoundError("no cached card mask for this run (replay never calls SAM)")


def _pixels(points):
    return [[round(float(x), 1), round(float(y), 1)] for x, y in points]


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
