"""Long-running build process for the web app: imports CadQuery once, then builds jobs from stdin.

Starting a new process per slider move spent about 5.5 s of 8.7 s just importing CadQuery.
Each job is one JSON line {"code": path, "output": path, "overrides": {...}}; the program runs
in a fresh namespace and the part is exported (STL/STEP by extension, or a top-view silhouette
mask for .npy, with "mm_per_pixel"); with "features": path it also writes the bounding box and the
top face's circular holes as JSON (for the 3D labels). The reply is one JSON
line {"ok": true} or {"ok": false, "error": "..."}. Programs are checked (check_code) by the
caller before they get here; webapp/builder.py restarts this process if a job hangs or it dies.
"""
import contextlib
import json
import sys
import traceback


def build(job):
    import cadquery as cq

    from candidates import FUNCTION_NAME

    with open(job["code"], encoding="utf-8") as file:
        code = file.read()
    namespace = {"__name__": "candidate"}
    exec(compile(code, job["code"], "exec"), namespace)
    result = namespace[FUNCTION_NAME](**job.get("overrides", {}))
    if not isinstance(result, cq.Workplane):
        result = cq.Workplane("XY").add(result)
    if job["output"].endswith(".npy"):  # top-view silhouette instead of a CAD file
        import numpy as np

        from render_silhouette import render_top_silhouette

        np.save(job["output"], render_top_silhouette(result, float(job["mm_per_pixel"])) > 0)
    else:
        cq.exporters.export(result, job["output"])
    if job.get("features"):
        with open(job["features"], "w", encoding="utf-8") as file:
            json.dump(features(result), file)


def features(result):
    """What the 3D labels point at: the bounding box and the full circles on the top face (holes)."""
    solid = result.findSolid()
    box = solid.BoundingBox()  # padded by a small tolerance; the top face's height comes from the vertices
    top = max(vertex.Z for vertex in solid.Vertices())
    holes = []
    for edge in solid.Edges():
        if edge.geomType() != "CIRCLE" or not edge.IsClosed():
            continue
        center = edge.arcCenter()
        if abs(center.z - top) < 1e-3:
            holes.append({"center": [round(center.x, 3), round(center.y, 3), round(center.z, 3)],
                          "diameter": round(2 * edge.radius(), 3)})
    return {"box": [round(v, 3) for v in (box.xmin, box.ymin, box.zmin, box.xmax, box.ymax, box.zmax)],
            "holes": holes}


def main():
    import cadquery  # noqa: F401  (load once, up front)

    print(json.dumps({"ready": True}), flush=True)
    for line in sys.stdin:
        try:
            with contextlib.redirect_stdout(sys.stderr):  # stdout carries only the replies
                build(json.loads(line))
            reply = {"ok": True}
        except Exception:
            reply = {"ok": False, "error": traceback.format_exc().strip().splitlines()[-1]}
        print(json.dumps(reply), flush=True)


if __name__ == "__main__":
    main()
