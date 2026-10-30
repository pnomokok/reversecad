"""Pattern B for an adapter plate: the new hole pattern the user asks for.

A pattern is {"holes": [{"x", "y", "d"} in mm, "label": str}: hole centers relative to the
pattern's own centre, diameters as clearance holes. Presets are fixed data (they work in the
online demo, which has no model); free text goes through Muse Spark Open (interpret_pattern) and
the same deterministic validation (validate_pattern). Nothing is placed until the user applies it.
"""
import json
import re
import time

import usage_ledger
from baseten_client import MODEL, make_client

# Clearance-hole diameters (mm) for metric screws, ISO 273 medium (normal) series. One table,
# used by the presets and quoted to the model; M3/M4/M5/M6 are what the presets and the prompt use.
ISO_273_MEDIUM = {"M3": 3.4, "M4": 4.5, "M5": 5.5, "M6": 6.6}

PRESETS = [
    {"id": "2xM5_60", "label": "2 \u00d7 M5 \u00b7 60 mm",
     "holes": [{"x": -30.0, "y": 0.0, "d": ISO_273_MEDIUM["M5"]},
               {"x": 30.0, "y": 0.0, "d": ISO_273_MEDIUM["M5"]}]},
    {"id": "4xM4_40x40", "label": "4 \u00d7 M4 \u00b7 40 \u00d7 40 mm",
     "holes": [{"x": -20.0, "y": -20.0, "d": ISO_273_MEDIUM["M4"]},
               {"x": 20.0, "y": -20.0, "d": ISO_273_MEDIUM["M4"]},
               {"x": -20.0, "y": 20.0, "d": ISO_273_MEDIUM["M4"]},
               {"x": 20.0, "y": 20.0, "d": ISO_273_MEDIUM["M4"]}]},
    {"id": "4xM3_30x30", "label": "4 \u00d7 M3 \u00b7 30 \u00d7 30 mm",
     "holes": [{"x": -15.0, "y": -15.0, "d": ISO_273_MEDIUM["M3"]},
               {"x": 15.0, "y": -15.0, "d": ISO_273_MEDIUM["M3"]},
               {"x": -15.0, "y": 15.0, "d": ISO_273_MEDIUM["M3"]},
               {"x": 15.0, "y": 15.0, "d": ISO_273_MEDIUM["M3"]}]},
]

# Sane ranges for a user-supplied pattern (an adapter plate is a hand-size flat part).
PATTERN_MIN_HOLES = 1
PATTERN_MAX_HOLES = 12
PATTERN_MIN_DIAMETER_MM = 1.0
PATTERN_MAX_DIAMETER_MM = 50.0
PATTERN_MAX_EXTENT_MM = 200.0  # |x| and |y| of any hole from the pattern centre
PATTERN_MAX_LABEL_CHARS = 80

REASONING_EFFORT = "low"  # a one-line pattern description; low answers in a few seconds
MAX_TOKENS = 4000
EXAMPLE = '"2 \u00d7 M5, 60 mm apart" or "4 \u00d7 M4 in a 40 \u00d7 40 mm square"'

PROMPT = """Turn a short hole-pattern description into a JSON hole pattern for an adapter plate.

Description: "{text}"

Rules:
- Holes are clearance holes; an M size means its ISO 273 medium diameter: {iso}.
  A bare diameter in mm ("two 6 mm holes") is used as given.
- Coordinates are in mm, relative to the pattern's own centre (its middle is (0, 0)).
  "60 mm apart" for two holes is x = -30 and x = +30 on one line; "in a 40 x 40 mm square"
  is x, y = +/-20. Without a layout, put two holes on a horizontal line, more holes on a square grid.
- "label" is a short name like the description, at most 80 characters.
- If the description has no hole count, sizes and spacings you can read, answer exactly: NO PATTERN.

Reply with JSON only, no other text:
{{"holes": [{{"x": <mm>, "y": <mm>, "d": <mm>}}], "label": "<short name>"}}"""


def validate_pattern(data):
    """(pattern, None) with the pattern normalized, or (None, error) when it is not usable.

    Checks the schema, the sane ranges and that no two holes overlap. Holes come back sorted by
    (x, y, d) so the same pattern always hashes the same; coordinates are rounded to 0.001 mm.
    """
    if not isinstance(data, dict) or not isinstance(data.get("holes"), list):
        return None, 'a pattern is {"holes": [{"x": mm, "y": mm, "d": mm}], "label": "..."}'
    holes = data["holes"]
    if not PATTERN_MIN_HOLES <= len(holes) <= PATTERN_MAX_HOLES:
        return None, f"a pattern has {PATTERN_MIN_HOLES}-{PATTERN_MAX_HOLES} holes ({len(holes)} given)"
    label = data.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > PATTERN_MAX_LABEL_CHARS:
        return None, "the pattern needs a short label (1-80 characters)"
    clean = []
    for hole in holes:
        if not isinstance(hole, dict):
            return None, "each hole is {\"x\": mm, \"y\": mm, \"d\": mm}"
        values = [hole.get(key) for key in ("x", "y", "d")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in values):
            return None, "each hole needs numeric x, y and d"
        x, y, d = (round(float(v), 3) for v in values)
        if abs(x) > PATTERN_MAX_EXTENT_MM or abs(y) > PATTERN_MAX_EXTENT_MM:
            return None, f"hole at ({x}, {y}) is outside \u00b1{PATTERN_MAX_EXTENT_MM:g} mm from the pattern centre"
        if not PATTERN_MIN_DIAMETER_MM <= d <= PATTERN_MAX_DIAMETER_MM:
            return None, (f"hole diameter {d} mm is outside "
                          f"{PATTERN_MIN_DIAMETER_MM:g}-{PATTERN_MAX_DIAMETER_MM:g} mm")
        clean.append({"x": x, "y": y, "d": d})
    for i, first in enumerate(clean):
        for second in clean[i + 1:]:
            distance = ((first["x"] - second["x"]) ** 2 + (first["y"] - second["y"]) ** 2) ** 0.5
            if distance < (first["d"] + second["d"]) / 2 - 1e-9:
                return None, (f"two holes overlap (centres {distance:.1f} mm apart, "
                              f"diameters {first['d']} and {second['d']} mm)")
    clean.sort(key=lambda h: (h["x"], h["y"], h["d"]))
    return {"holes": clean, "label": label.strip()}, None


def _number(value):
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def summarize_pattern(pattern):
    """One computed line about a validated pattern, e.g. "2 holes · Ø5.5 · 60 mm apart"."""
    holes = pattern["holes"]
    diameters = sorted({h["d"] for h in holes})
    sizes = f"\u00d8{_number(diameters[0])}" if len(diameters) == 1 else \
        f"\u00d8{_number(diameters[0])}\u2013\u00d8{_number(diameters[-1])}"
    if len(holes) == 1:
        layout = "single hole"
    elif len(holes) == 2:
        apart = ((holes[0]["x"] - holes[1]["x"]) ** 2 + (holes[0]["y"] - holes[1]["y"]) ** 2) ** 0.5
        layout = f"{_number(apart)} mm apart"
    else:
        width = max(h["x"] for h in holes) - min(h["x"] for h in holes)
        height = max(h["y"] for h in holes) - min(h["y"] for h in holes)
        layout = f"spans {_number(width)} \u00d7 {_number(height)} mm"
    count = f"{len(holes)} hole" + ("s" if len(holes) != 1 else "")
    return f"{count} \u00b7 {sizes} \u00b7 {layout}"


def parse_pattern_answer(text):
    """(pattern, None) from the model's answer, or (None, a message for the user). Never guesses."""
    if (text or "").strip() == "NO PATTERN":
        return None, f"no hole pattern in that text (try {EXAMPLE})"
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    pattern, error = validate_pattern(data)
    if pattern is not None:
        return pattern, None
    if data is None:
        return None, f"I could not read a hole pattern in that text (try {EXAMPLE})"
    return None, error


def interpret_pattern(text, ledger_folder=None, client=None):
    """{"pattern", "summary", "seconds"} for a free-text description; raises RuntimeError when no
    pattern could be read (the caller shows the message; nothing is used)."""
    listing = ", ".join(f"{size} = {diameter}" for size, diameter in ISO_273_MEDIUM.items())
    started = time.perf_counter()
    response = (client or make_client()).chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT,
        messages=[{"role": "user", "content": PROMPT.format(text=text.strip(), iso=listing)}])
    seconds = round(time.perf_counter() - started, 1)
    if ledger_folder is not None:
        usage_ledger.record_response(ledger_folder, usage_ledger.SPARK_OPEN, "adapter pattern", response.model_dump(),
                                     seconds)
    pattern, error = parse_pattern_answer(response.choices[0].message.content)
    if pattern is None:
        raise RuntimeError(error)
    return {"pattern": pattern, "summary": summarize_pattern(pattern), "seconds": seconds}
