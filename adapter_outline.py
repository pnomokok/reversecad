"""Adapter plate outline: the deterministic fallback and the checks every outline passes.

The fallback is a rounded rectangle around all holes (pattern A + placed pattern B) with
MIN_WALL_MM of margin; its program is written here with partkit, like the cover and spacer.
check_adapter scores any built outline - fallback, Muse Spark Open or Muse Wonder repair -
against the expected holes: right holes at the right positions (HOLE_TOLERANCE_MM, the same
0.5 mm the deviation check allows), every hole edge at least MIN_WALL_MM from the outline,
a single solid, no extra holes.
"""
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import adapter_place
import usage_ledger
from adapter_place import MIN_WALL_MM
from baseten_client import MODEL, make_client
from candidates import MAX_TOKENS, TEMPERATURE, extract_python_block, partkit_reference, style_for
from design_intent import parameters as program_parameters
from deviation_check import SMALL_LIMIT_MM as HOLE_TOLERANCE_MM

# Must not exceed MIN_WALL_MM: with r <= margin, a hole tucked into a corner is nearest to a
# fillet endpoint at distance >= margin + hole radius (its centre is past the arc centre in x and y),
# so the rounded corner never eats into the margin. Larger radii break small corner holes out.
FALLBACK_CORNER_RADIUS_MM = 2.0
ADAPTER_CANDIDATE_COUNT = 3
ADAPTER_MAX_PARALLEL = 3
DEFAULT_REASONING_EFFORT = "medium"

PROMPT_TEMPLATE = """You write CadQuery (Python) code for a flat adapter plate that connects two hole patterns.

All hole positions below are final, in absolute millimeters (X = u, Y = v). Do not move them, do not
add holes, do not leave any out: the part must have exactly these {count} through-holes.

Pattern A (the existing part, {count_a} holes):
{holes_a}

Pattern B (the new pattern, {count_b} holes):
{holes_b}

Plate rules:
- The outline is a clean plate shape (usually a rectangle, possibly with rounded corners) that
  encloses every hole. Every hole edge must be at least {wall} mm from the outline.
- One single solid. Holes within {tolerance} mm in position and size, or the part is rejected.
- Thickness cannot be seen from the holes; use {thickness} mm, bottom face at Z = 0.
- Define exactly one function `def build_part(...)` that returns a cadquery Workplane.
- Every dimension is a keyword argument with its default taken from the numbers above: overall size
  (e.g. length, width), the edge margin, one hole diameter per group of equal holes.
- Build the part with the helper library `partkit` (`import partkit as pk`); it takes absolute
  coordinates and is tested. Plain CadQuery is allowed for anything it does not cover:
{partkit}
- Only `import cadquery as cq`, `import partkit as pk` and `import math`. Do not use show_object, file I/O
  or print.
- Reply with a single ```python code block and nothing else."""


def _point(point):
    return f"({point[0]!r}, {point[1]!r})"


def _points(name, points):
    return [f"{name} = [", *[f"    {_point(p)}," for p in points], "]", ""]


def fallback_source(holes_a, holes_b, thickness, label_b, source_program="the original"):
    """The fallback adapter program (text): a rounded rectangle with margin around every hole.

    holes_a are the original's top-face holes (circles and fixed polygons, as measured); holes_b
    are the placed pattern B circles ({"x", "y", "d"}). Only the thickness and the hole diameters
    are parameters; the outline that encloses the holes is fixed data.
    """
    groups_a, groups_b = {}, {}
    for hole in holes_a:
        if hole["type"] == "circle":
            groups_a.setdefault(hole["diameter"], []).append(hole["center"])
    for hole in holes_b:
        groups_b.setdefault(hole["d"], []).append([hole["x"], hole["y"]])
    shaped = [hole["points"] for hole in holes_a if hole["type"] != "circle"]

    extremes = []  # every hole's reach, so the rectangle encloses them all
    for diameter, centers in list(groups_a.items()) + list(groups_b.items()):
        for x, y in centers:
            extremes += [(x - diameter / 2, y - diameter / 2), (x + diameter / 2, y + diameter / 2)]
    for corners in shaped:
        extremes += [tuple(p) for p in corners]
    x0 = min(p[0] for p in extremes) - MIN_WALL_MM
    x1 = max(p[0] for p in extremes) + MIN_WALL_MM
    y0 = min(p[1] for p in extremes) - MIN_WALL_MM
    y1 = max(p[1] for p in extremes) + MIN_WALL_MM
    length, width = round(x1 - x0, 3), round(y1 - y0, 3)
    center = (round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3))
    # The margin alone makes each side over 4 mm, so a fillet always fits.
    radius = round(min(FALLBACK_CORNER_RADIUS_MM, length / 2 - 0.1, width / 2 - 0.1), 3)

    arguments = [f"    thickness={thickness!r},"]
    data = [f"CENTER = {_point(center)}", f"LENGTH = {length!r}", f"WIDTH = {width!r}", ""]
    body = ["    part = (cq.Workplane(\"XY\", origin=CENTER).rect(LENGTH, WIDTH).extrude(thickness)"
            f".edges(\"|Z\").fillet({radius!r}))"]
    for tag, groups in (("a", groups_a), ("b", groups_b)):
        for i, (diameter, centers) in enumerate(groups.items(), 1):
            parameter = f"hole_diameter_{tag}" if len(groups) == 1 else f"hole_diameter_{tag}_{i}"
            arguments.append(f"    {parameter}={diameter!r},")
            data += _points(f"ROUND_HOLES_{tag.upper()}_{i}", centers)
            body.append(f"    part = pk.hole_pattern(part, ROUND_HOLES_{tag.upper()}_{i}, {parameter})")
    if shaped:
        data += ["SHAPED_HOLES_A = [", *[f"    [{', '.join(map(_point, points))}]," for points in shaped], "]", ""]
        body += ["    for corners in SHAPED_HOLES_A:", "        part = pk.cut_polygon(part, corners)"]
    return "\n".join([
        f'"""Adapter plate matching {source_program}: pattern A plus pattern B ({label_b}).',
        "Fallback outline by adapter_outline.py: a rounded rectangle with margin around every hole.\"\"\"",
        "import cadquery as cq",
        "import partkit as pk",
        "",
        *data,
        "",
        "def build_part(",
        *arguments,
        "):",
        *body,
        "    return part",
        "",
    ])


def _describe(tag, index, hole):
    at = adapter_place.hole_center(hole)
    return f"pattern {tag} hole {index + 1} at ({at[0]:.2f}, {at[1]:.2f})"


def check_adapter(built, holes_a, holes_b):
    """{"ok", "reasons", "matched", "min_margin_mm"} for a built adapter profile.

    holes_a/holes_b are the expected holes in wall form (adapter_place.profile_hole for A,
    {"circle": (x, y, d)} for placed B). Reasons name the hole and the numbers, for the screen.
    """
    reasons = []
    if built.get("solid_count", 1) != 1:
        reasons.append(f"the program built {built.get('solid_count', 1)} solids, not one")
    expected = [("A", i, h) for i, h in enumerate(holes_a)] + [("B", i, h) for i, h in enumerate(holes_b)]
    built_holes = [adapter_place.profile_hole(h) for h in built["holes"]]

    def pair_up(want_circle):
        """Greedy closest-first pairs of expected and built holes of one kind, plus the missing."""
        wanted = [(tag, i, h) for tag, i, h in expected if ("circle" in h) == want_circle]
        have = [h for h in built_holes if ("circle" in h) == want_circle]
        distances = sorted((math.dist(adapter_place.hole_center(h), adapter_place.hole_center(g)), k, j)
                           for k, (_, _, h) in enumerate(wanted) for j, g in enumerate(have))
        pairs, taken_wanted, taken_have = [], set(), set()
        for _, k, j in distances:
            if k not in taken_wanted and j not in taken_have:
                taken_wanted.add(k)
                taken_have.add(j)
                pairs.append((wanted[k], have[j]))
        missing = [wanted[k] for k in range(len(wanted)) if k not in taken_wanted]
        extra = [have[j] for j in range(len(have)) if j not in taken_have]
        return pairs, missing, extra

    circles, missing_circles, extra_circles = pair_up(True)
    polys, missing_polys, extra_polys = pair_up(False)
    matched = 0
    for (tag, i, want), got in circles:
        position = math.dist(adapter_place.hole_center(want), adapter_place.hole_center(got))
        size = abs(want["circle"][2] - got["circle"][2])
        if position > HOLE_TOLERANCE_MM or size > HOLE_TOLERANCE_MM:
            reasons.append(f"{_describe(tag, i, want)}: built {position:.2f} mm off, "
                           f"Ø{got['circle'][2]:.2f} instead of Ø{want['circle'][2]:.2f}")
        else:
            matched += 1
    for (tag, i, want), got in polys:
        position = math.dist(adapter_place.hole_center(want), adapter_place.hole_center(got))
        corners = f"{len(got['polygon'])} corners, expected {len(want['polygon'])}" \
            if len(got["polygon"]) != len(want["polygon"]) else ""
        if position > HOLE_TOLERANCE_MM or corners:
            reasons.append(f"{_describe(tag, i, want)}: built {position:.2f} mm off"
                           + (f", {corners}" if corners else ""))
        else:
            matched += 1
    for tag, i, want in missing_circles + missing_polys:
        reasons.append(f"{_describe(tag, i, want)}: missing (no hole within {HOLE_TOLERANCE_MM} mm)")
    for got in extra_circles + extra_polys:
        at = adapter_place.hole_center(got)
        what = f"Ø{got['circle'][2]:.2f}" if "circle" in got else f"{len(got['polygon'])}-corner hole"
        reasons.append(f"extra hole at ({at[0]:.2f}, {at[1]:.2f}), {what}")
    margins = [adapter_place.hole_to_outline(h, built["outline"]) for h in built_holes]
    for hole, margin in zip(built_holes, margins):
        if margin < MIN_WALL_MM - 1e-9:
            at = adapter_place.hole_center(hole)
            reasons.append(f"hole at ({at[0]:.2f}, {at[1]:.2f}) is {margin:.2f} mm from the edge "
                           f"(at least {MIN_WALL_MM} mm needed)")
    return {"ok": not reasons, "reasons": reasons, "matched": f"{matched}/{len(expected)}",
            "min_margin_mm": round(min(margins), 3) if margins else None}


def _hole_lines(holes):
    lines = []
    for hole in holes:
        if "circle" in hole:
            x, y, d = hole["circle"]
            lines.append(f"- circle: center [{x:.2f}, {y:.2f}], diameter {d:.2f}")
        else:
            corners = ", ".join(f"[{x:.2f}, {y:.2f}]" for x, y in hole["polygon"])
            lines.append(f"- polygon hole with corners: {corners}")
    return "\n".join(lines)


def build_adapter_prompt(holes_a, holes_b, thickness, style=None):
    """Prompt text for an outline around the expected holes (wall form), at this thickness.

    style (a key of candidates.STYLES) adds that approach; None leaves it out.
    """
    prompt = PROMPT_TEMPLATE.format(
        count=len(holes_a) + len(holes_b), count_a=len(holes_a), count_b=len(holes_b),
        holes_a=_hole_lines(holes_a), holes_b=_hole_lines(holes_b), wall=MIN_WALL_MM,
        tolerance=HOLE_TOLERANCE_MM, thickness=round(float(thickness), 2), partkit=partkit_reference())
    if style:
        from candidates import STYLES

        prompt = prompt.replace("- Reply with a single ```python code block",
                                f"- Approach for this program: {STYLES[style]}\n- Reply with a single ```python code block")
    return prompt


def _request_text(client, prompt, reasoning_effort):
    started = time.perf_counter()
    extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else {}
    response = client.chat.completions.create(**extra, model=MODEL, max_tokens=MAX_TOKENS,
                                              temperature=TEMPERATURE, messages=[{"role": "user", "content": prompt}])
    result = response.model_dump()
    result["elapsed_s"] = round(time.perf_counter() - started, 1)
    return result


def search_adapter_outlines(holes_a, holes_b, thickness, build, out_dir, tag,
                            count=ADAPTER_CANDIDATE_COUNT, ledger_folder=None, client=None,
                            reasoning_effort=DEFAULT_REASONING_EFFORT):
    """Ask Muse Spark Open for `count` outlines and check each; returns rows in candidate order.

    Text-only requests (there is no photo to send: the hole lists are the whole task). build(path)
    returns (profile, error) for a candidate file; candidate files and raw responses are written to
    out_dir as {tag}_cand{i}.py/.json. A failed request or build becomes {"error": ...}, never an
    exception. Needs BASETEN_API_KEY unless the client is faked (tests).
    """
    from candidates import check_code

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = client or make_client()
    prompts = {i: build_adapter_prompt(holes_a, holes_b, thickness, style_for(i)) for i in range(1, count + 1)}
    responses = {}
    with ThreadPoolExecutor(max_workers=min(count, ADAPTER_MAX_PARALLEL)) as pool:
        futures = {pool.submit(_request_text, client, prompts[i], reasoning_effort): i for i in prompts}
        for future in as_completed(futures):
            try:
                responses[futures[future]] = future.result()
            except Exception as error:
                responses[futures[future]] = {"error": f"{type(error).__name__}: {error}"}
    rows = []
    for i in range(1, count + 1):
        response = responses[i]
        (out_dir / f"{tag}_cand{i}_prompt.txt").write_text(prompts[i], encoding="utf-8")
        (out_dir / f"{tag}_cand{i}_response.json").write_text(json.dumps(response), encoding="utf-8")
        if ledger_folder is not None:
            usage_ledger.record_response(ledger_folder, usage_ledger.SPARK_OPEN, f"adapter outline {i}", response)
        path = out_dir / f"{tag}_cand{i}.py"
        code = None if "error" in response else extract_python_block(response["choices"][0]["message"]["content"])
        usage = (response.get("usage") or {}) if isinstance(response, dict) else {}
        row = {"candidate": i, "style": style_for(i), "file": str(path),
               "seconds": response.get("elapsed_s"), "input_tokens": usage.get("prompt_tokens"),
               "output_tokens": usage.get("completion_tokens")}
        if "error" in response:
            row["error"] = f"request failed: {response['error']}"
        elif code is None:
            row["error"] = "no python code block (finish=" \
                f"{response['choices'][0].get('finish_reason')})"
        elif (problems := check_code(code)):
            row["error"] = "rejected before running: " + "; ".join(problems)
        else:
            path.write_text(code, encoding="utf-8")
            profile, error = build(path)
            if error:
                row["error"] = error
            else:
                report = check_adapter(profile, holes_a, holes_b)
                row.update({k: report[k] for k in ("ok", "reasons", "matched", "min_margin_mm")})
                row["parameter_count"] = len(program_parameters(code))
        rows.append(row)
    return rows


def pick_adapter_winner(rows):
    """The passing row with the fewest parameters (first on ties), or None."""
    passing = [row for row in rows if row.get("ok")]
    return min(passing, key=lambda row: (row["parameter_count"], row["candidate"])) if passing else None
