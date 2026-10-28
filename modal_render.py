"""Build candidate programs on Modal: CadQuery runs in Modal containers, many at once.

Only the heavy step moves: building the program and rendering its top-view silhouette (what
run_candidate.py does in a local process). Scoring (IoU, measurements, limits) stays local. Programs
are screened with candidates.check_code before they are sent, as for local runs.

    with modal_render.app.run():
        mask, error = modal_render.render(path, 0.1)   # same contract as run_candidate.run_candidate

The Modal image pins the local versions (Python 3.13, CadQuery 2.8.0, OCP 7.9.3.1.1).
"""
import io
from pathlib import Path

import modal
import numpy as np

from candidates import check_code

app = modal.App("reversecad-render")
image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("libgl1", "libglib2.0-0")
    .pip_install("cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "numpy==2.5.4", "opencv-python-headless")
    .add_local_python_source("partkit", "render_silhouette")
)


@app.function(image=image, cpu=1.0, memory=1024, timeout=180, max_containers=40)
def build_silhouette(code: str, mm_per_pixel: float):
    """(mask as .npy bytes, None) or (None, the error's last line) for one program."""
    import traceback

    import cadquery as cq

    from render_silhouette import render_top_silhouette

    try:
        namespace = {"__name__": "candidate"}
        exec(compile(code, "candidate.py", "exec"), namespace)
        result = namespace["build_part"]()
        if not isinstance(result, cq.Workplane):
            result = cq.Workplane("XY").add(result)
        stream = io.BytesIO()
        np.save(stream, render_top_silhouette(result, mm_per_pixel) > 0)
        return stream.getvalue(), None
    except Exception:
        return None, traceback.format_exc().strip().splitlines()[-1]


def render(code_path, mm_per_pixel):
    """Like run_candidate.run_candidate, on Modal; the mask is also saved next to the program."""
    code_path = Path(code_path)
    problems = check_code(code_path.read_text(encoding="utf-8"))
    if problems:
        return None, "rejected before running: " + "; ".join(problems)
    data, error = build_silhouette.remote(code_path.read_text(encoding="utf-8"), float(mm_per_pixel))
    if error:
        return None, error
    mask = np.load(io.BytesIO(data))
    np.save(code_path.with_suffix(".default.mask.npy"), mask)
    return mask, None
