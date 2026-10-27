"""Generate candidate CadQuery programs with Muse Spark Open and screen them before running.

The model gets the part's top-view mask (white = part, black = background) and
the measurement table; numbers must come from the table. Requests run in
parallel. Before any candidate is executed, check_code() rejects imports other
than cadquery/math and calls such as open/exec/eval: the code comes from a
language model and runs on this machine.
"""
import ast
import inspect
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

import partkit
from baseten_client import MODEL, image_data_url, make_client

MAX_TOKENS = 16000  # reasoning tokens count toward this limit; 8000 ran out before any code
TEMPERATURE = 0.8  # some variety between candidates
MAX_PARALLEL_REQUESTS = 5
FUNCTION_NAME = "build_part"
ALLOWED_IMPORTS = {"cadquery", "math", "partkit"}
BLOCKED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "breakpoint", "exit", "quit", "show_object",
}

PROMPT_TEMPLATE = """You write CadQuery (Python) code for a flat, prismatic part.

The image is the part's top-down orthographic silhouette: white = part, black = background.
Use it only to understand the shape (outline, holes). Do not measure pixels.

Measurement table in millimeters, measured by deterministic code. Take every number from here:
{table}

Coordinates are [u, v]: u along the part's length, v along its width, origin at the center of the
outline's bounding rectangle. "outline.polygon_mm" lists the outer boundary's corners in order.
Holes are through-holes. Each hole has a "shape":
- "circle": use diameter_mm;
- "rectangle", "slot" (semicircular ends) or "ellipse": use length_mm (overall, end to end), width_mm and
  angle_deg (rotation of its length from the u axis). CadQuery's `slot2D(length, diameter, angle)` takes the
  overall end-to-end length; `ellipse(x_radius, y_radius)` takes half the length and half the width;
- "polygon": use polygon_mm, its corners in order.
Thickness cannot be seen from the top; use 3.0 mm.

Requirements:
- Define exactly one function `def {function}(...)` that returns a cadquery Workplane.
- Every dimension is a keyword argument with its default taken from the table, so it can be edited later.
- Capture the design intent with few, meaningfully named parameters, the way a designer would:
  * holes of the same size share one parameter (e.g. hole_diameter);
  * symmetric or repeated layouts are built from that pattern (e.g. edge_margin, hole_spacing), so changing
    the overall length or width keeps the symmetry and the distances to the edges;
  * features such as tabs, arms or notches get their own dimensions (e.g. tab_length, tab_width, arm_width)
    instead of a list of raw corner coordinates.
  Values that differ by less than about 0.5 mm are measurement noise of the same design value.
- Irregular measured edges (torn or hand-cut, slightly wobbly hole outlines) may be replaced by the clean
  shape a designer would have meant: a straight edge, a rectangle, an arc. Limits with the default arguments,
  or the part is rejected: outline length and width within max(1 mm, 2%) of the table; every outline corner
  within that distance of your outline (0.5 mm for corners of features with an edge under 20 mm, such as tabs
  and notches); holes within 0.5 mm in size and position.
- Placement: X = u, Y = v, bottom face at Z = 0, top face at Z = thickness.
- Build the part with the helper library `partkit` (`import partkit as pk`); it takes absolute coordinates
  and is tested. Plain CadQuery is allowed for anything it does not cover. You decide the structure and the
  parameters; the helpers only do the geometry:
{partkit}
- Only `import cadquery as cq`, `import partkit as pk` and `import math`. Do not use show_object, file I/O
  or print.
- Reply with a single ```python code block and nothing else."""


HOLE_FIELDS = {  # what the model needs per hole shape; quality scores are left out
    "circle": ["shape", "center_from_part_center_mm", "diameter_mm"],
    "rectangle": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "slot": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "ellipse": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "polygon": ["shape", "center_from_part_center_mm", "polygon_mm"],
}


def partkit_reference():
    """One line per partkit function: signature and docstring, generated so it never drifts from the code."""
    lines = []
    for name in partkit.__all__:
        function = getattr(partkit, name)
        doc = " ".join(inspect.getdoc(function).split())
        lines.append(f"    pk.{name}{inspect.signature(function)}: {doc}")
    return "\n".join(lines)


def build_prompt(view):
    """Prompt text for a model view of the table (see model_view.py)."""
    shown = {"outline": {key: view["outline"][key] for key in ("length_mm", "width_mm", "vertex_count", "polygon_mm")},
             "hole_count": view["hole_count"],
             "holes": [{field: hole[field] for field in HOLE_FIELDS[hole["shape"]]} for hole in view["holes"]]}
    return PROMPT_TEMPLATE.format(table=json.dumps(shown, indent=2), function=FUNCTION_NAME,
                                  partkit=partkit_reference())


def extract_python_block(text):
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text or "", re.DOTALL)
    return match.group(1) if match else None


def check_code(code):
    """Return a list of problems; an empty list means the code may be executed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [f"syntax error: {error}"]
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module or ""]
        else:
            modules = []
        for module in modules:
            if module.split(".")[0] not in ALLOWED_IMPORTS:
                problems.append(f"import not allowed: {module}")
        if isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            problems.append(f"name not allowed: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"dunder attribute not allowed: {node.attr}")
    has_function = any(isinstance(n, ast.FunctionDef) and n.name == FUNCTION_NAME for n in tree.body)
    if not has_function:
        problems.append(f"no top-level function named {FUNCTION_NAME}")
    return problems


def _request_one(client, prompt, image_url):
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=TEMPERATURE,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        }],
    )
    result = response.model_dump()
    result["elapsed_s"] = round(time.perf_counter() - started, 1)  # wall time of this request
    return result


def generate_candidates(view, mask_image_path, count):
    """Return (prompt, `count` results: each the raw response dict, or {"error": message}).

    view is the model's view of the measurement table (model_view.py).
    """
    client = make_client()
    prompt = build_prompt(view)
    image_url = image_data_url(mask_image_path)
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(count, MAX_PARALLEL_REQUESTS)) as pool:
        futures = [pool.submit(_request_one, client, prompt, image_url) for _ in range(count)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as error:  # keep the other candidates if one request fails
                results.append({"error": f"{type(error).__name__}: {error}"})
    batch_seconds = round(time.perf_counter() - started, 1)
    for result in results:
        result["batch_elapsed_s"] = batch_seconds  # all requests, MAX_PARALLEL_REQUESTS at a time
    return prompt, results
