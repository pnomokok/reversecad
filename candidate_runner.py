"""Run one candidate CadQuery file in its own process and save its top-view silhouette.

Called by run_candidate() with a timeout, so a crashing or hanging candidate
cannot take the main program down. Errors go to stderr; exit code 0 = success.

Usage: python candidate_runner.py <candidate.py> <out_mask.npy> <mm_per_pixel> [overrides as JSON]
The optional overrides are keyword arguments for build_part, e.g. '{"hole_diameter": 7.0}'.
"""
import json
import sys
import traceback


def main(code_path, output_path, mm_per_pixel, overrides="{}"):
    import cadquery as cq
    import numpy as np

    from candidates import FUNCTION_NAME
    from render_silhouette import render_top_silhouette

    with open(code_path, encoding="utf-8") as file:
        code = file.read()
    namespace = {"__name__": "candidate"}
    exec(compile(code, code_path, "exec"), namespace)
    result = namespace[FUNCTION_NAME](**json.loads(overrides))
    if not isinstance(result, cq.Workplane):
        result = cq.Workplane("XY").add(result)  # a bare Shape is also accepted
    mask = render_top_silhouette(result, float(mm_per_pixel))
    np.save(output_path, mask > 0)


if __name__ == "__main__":
    try:
        main(*sys.argv[1:5])
    except Exception:
        traceback.print_exc()
        sys.exit(1)
