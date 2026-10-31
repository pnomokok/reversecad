"""Design-intent test: do a program's parameters behave like a designer's would?

Each check changes a parameter, rebuilds the part in a separate process and
measures the result:
- shared hole diameter: for each group of equal true holes (2 or more), is there
  one parameter that resizes all of them together and nothing else?
- length change (+10 mm on the parameter that sets the outline length): does the
  part keep the true part's symmetry, and do off-axis holes keep their distance
  to the nearer end (edge margin)?
- parameter count.
"""
import ast

import numpy as np

from part_measurements import measure_part
from run_candidate import run_candidate

MM_PER_PIXEL = 0.1
SCALE = np.diag([MM_PER_PIXEL, MM_PER_PIXEL, 1.0])
DIAMETER_STEP_MM = 1.0
LENGTH_STEP_MM = 10.0
MIN_MIRROR_IOU = 0.98


def parameters(code):
    """(name, default) pairs of build_part's arguments; default is None if not a literal."""
    tree = ast.parse(code)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "build_part")
    args = function.args
    pairs = []
    positional = args.args
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in list(zip(positional, defaults)) + list(zip(args.kwonlyargs, args.kw_defaults)):
        try:
            value = ast.literal_eval(default) if default is not None else None
        except ValueError:
            value = None
        pairs.append((arg.arg, value))
    return pairs


def replace_defaults(source, values):
    """A program's source with build_part's defaults replaced by `values` (name -> number).

    Only the default values change (located by the parser, replaced from the end of the text so
    earlier positions stay valid); the rest of the code is kept as written.
    """
    function = next(node for node in ast.parse(source).body
                    if isinstance(node, ast.FunctionDef) and node.name == "build_part")
    args = function.args
    pairs = list(zip(args.args[len(args.args) - len(args.defaults):], args.defaults))
    pairs += [(arg, default) for arg, default in zip(args.kwonlyargs, args.kw_defaults) if default is not None]
    lines = source.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits = []
    for arg, default in pairs:
        if arg.arg in values:
            start = offsets[default.lineno - 1] + default.col_offset
            end = offsets[default.end_lineno - 1] + default.end_col_offset
            edits.append((start, end, repr(round(float(values[arg.arg]), 4))))
    for start, end, text in sorted(edits, reverse=True):
        source = source[:start] + text + source[end:]
    return source


def symmetry_axes(truth, tolerance=0.01):
    """Mirror axes of the true part: 'left-right' (u -> -u) and/or 'top-bottom' (v -> -v)."""
    def same(points_a, points_b):
        return all(min(np.linalg.norm(np.array(a) - np.array(b)) for b in points_b) < tolerance for a in points_a)

    corners = [tuple(c) for c in truth["outline_mm"]]
    holes = [(*h["center_from_part_center_mm"], h["diameter_mm"]) for h in truth["holes"]]
    axes = []
    for name, (su, sv) in [("left-right", (-1, 1)), ("top-bottom", (1, -1))]:
        mirrored_corners = [(su * u, sv * v) for u, v in corners]
        mirrored_holes = [(su * u, sv * v, d) for u, v, d in holes]
        if same(mirrored_corners, corners) and same(mirrored_holes, holes):
            axes.append(name)
    return axes


def mirror_iou(mask, axis):
    ys, xs = np.nonzero(mask)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    mirrored = np.fliplr(crop) if axis == "left-right" else np.flipud(crop)
    return np.count_nonzero(crop & mirrored) / np.count_nonzero(crop | mirrored)


def _equal_hole_groups(truth):
    groups = {}
    for hole in truth["holes"]:
        groups.setdefault(hole["diameter_mm"], []).append(hole)
    return {d: holes for d, holes in groups.items() if len(holes) >= 2}


def evaluate(code_path, truth):
    params = parameters(open(code_path, encoding="utf-8").read())
    numeric = {name: value for name, value in params if isinstance(value, (int, float)) and not isinstance(value, bool)}
    report = {"parameter_count": len(params), "parameters": [name for name, _ in params]}

    base_mask, error = run_candidate(code_path, MM_PER_PIXEL, tag="intent_base")
    if error:
        report["error"] = error
        return report
    base = measure_part(base_mask, SCALE)

    def rebuilt(name, value, tag):
        mask, _ = run_candidate(code_path, MM_PER_PIXEL, overrides={name: value}, tag=tag)
        return mask

    # 1. One parameter per group of equal holes?
    groups = _equal_hole_groups(truth)
    report["hole_diameter_parameter"] = None
    if groups:
        found = []
        for diameter, group in groups.items():
            match = None
            for name, value in numeric.items():
                if abs(value - diameter) > 0.5:
                    continue
                mask = rebuilt(name, value + DIAMETER_STEP_MM, f"intent_d_{name}")
                if mask is None:
                    continue
                changed = measure_part(mask, SCALE)
                if changed["hole_count"] != base["hole_count"]:
                    continue
                growth = [b["diameter_mm"] - a["diameter_mm"] for a, b in zip(base["holes"], changed["holes"])]
                grown = sum(1 for g in growth if abs(g - DIAMETER_STEP_MM) < 0.4)
                unchanged = sum(1 for g in growth if abs(g) < 0.3)
                if grown == len(group) and grown + unchanged == len(growth):
                    match = name
                    break
            found.append(match)
        report["hole_diameter_linked"] = all(found)
        report["hole_diameter_parameter"] = found
    else:
        report["hole_diameter_linked"] = None  # no repeated holes in this part

    # 2. Change the length: symmetry and edge margins kept?
    axes = symmetry_axes(truth)
    report["symmetry_axes"] = axes
    report["length_parameter"] = None
    off_axis = [h for h in base["holes"] if abs(h["center_from_part_center_mm"][0]) > 1.0]
    report["symmetric_after_length_change"] = False if axes else None
    report["edge_margin_kept"] = False if off_axis else None
    base_length = base["outline"]["length_mm"]
    for name, value in numeric.items():
        if abs(value - base_length) > 0.6:
            continue
        mask = rebuilt(name, value + LENGTH_STEP_MM, f"intent_len_{name}")
        if mask is None:
            continue
        changed = measure_part(mask, SCALE)
        if abs(changed["outline"]["length_mm"] - base_length - LENGTH_STEP_MM) > 0.5:
            continue  # this parameter does not set the length
        report["length_parameter"] = name
        if axes:
            report["symmetric_after_length_change"] = all(mirror_iou(mask, axis) >= MIN_MIRROR_IOU for axis in axes)
        if off_axis and changed["hole_count"] == base["hole_count"]:
            kept = []
            for a, b in zip(base["holes"], changed["holes"]):
                ua, ub = abs(a["center_from_part_center_mm"][0]), abs(b["center_from_part_center_mm"][0])
                if ua > 1.0:
                    margin_before = base_length / 2 - ua
                    margin_after = changed["outline"]["length_mm"] / 2 - ub
                    kept.append(abs(margin_after - margin_before) < 0.3)
            report["edge_margin_kept"] = all(kept)
        break
    return report
