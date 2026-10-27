"""Generate candidate CadQuery programs with Muse Spark Open and screen them before running.

The model gets the part's top-view mask (white = part, black = background) and
the measurement table; numbers must come from the table. Requests run in
parallel. Before any candidate is executed, check_code() rejects imports other
than cadquery/math and calls such as open/exec/eval: the code comes from a
language model and runs on this machine.
"""
import ast
import json
import re
from concurrent.futures import ThreadPoolExecutor

from baseten_client import MODEL, image_data_url, make_client

MAX_TOKENS = 16000  # reasoning tokens count toward this limit; 8000 ran out before any code
TEMPERATURE = 0.8  # some variety between candidates
MAX_PARALLEL_REQUESTS = 5
FUNCTION_NAME = "build_part"
ALLOWED_IMPORTS = {"cadquery", "math"}
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
  With the default arguments the part must still match the table within about 0.5 mm.
- Placement: X = u, Y = v, bottom face at Z = 0, top face at Z = thickness.
- Place holes at their absolute [u, v] coordinates, e.g. with `.pushPoints([...])`. Avoid `.center()` for this:
  it moves the workplane origin cumulatively, so a second `.center()` is relative to the first.
- Draw a polygon outline with `.polyline(points).close()` using the full list of corners. Do not combine
  `.moveTo(first)` with `.polyline(rest)`: polyline drops the current point by default, losing a corner.
- Only `import cadquery as cq` (and `import math` if needed). Do not use show_object, file I/O or print.
- Reply with a single ```python code block and nothing else."""


HOLE_FIELDS = {  # what the model needs per hole shape; quality scores are left out
    "circle": ["shape", "center_from_part_center_mm", "diameter_mm"],
    "rectangle": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "slot": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "ellipse": ["shape", "center_from_part_center_mm", "length_mm", "width_mm", "angle_deg"],
    "polygon": ["shape", "center_from_part_center_mm", "polygon_mm"],
}


def build_prompt(table):
    shown = {key: value for key, value in table.items() if key != "center_on_table_mm"}  # irrelevant to the model
    shown["holes"] = [{field: hole[field] for field in HOLE_FIELDS[hole["shape"]]} for hole in table["holes"]]
    return PROMPT_TEMPLATE.format(table=json.dumps(shown, indent=2), function=FUNCTION_NAME)


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
    return response.model_dump()


def generate_candidates(table, mask_image_path, count):
    """Return (prompt, `count` results: each the raw response dict, or {"error": message})."""
    client = make_client()
    prompt = build_prompt(table)
    image_url = image_data_url(mask_image_path)
    with ThreadPoolExecutor(max_workers=min(count, MAX_PARALLEL_REQUESTS)) as pool:
        futures = [pool.submit(_request_one, client, prompt, image_url) for _ in range(count)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as error:  # keep the other candidates if one request fails
                results.append({"error": f"{type(error).__name__}: {error}"})
    return prompt, results
