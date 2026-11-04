"""Long-running build process for the web app: imports CadQuery once, then builds jobs from stdin.

Starting a new process per slider move spent about 5.5 s of 8.7 s just importing CadQuery.
Each job is one JSON line {"code": path, "output": path, "overrides": {...}}; the program runs
in a fresh namespace and the part is exported (STL/STEP by extension, or a top-view silhouette
mask for .npy, with "mm_per_pixel"); with "features": path it also writes the bounding box and the
top face's circular holes as JSON (for the 3D labels). With "compare_to": another program, it writes
the material the program adds to that one (STL at "output"; what it removes at "removed_output") and
the volumes as JSON at "features" (for a completion suggestion). With "assembly": a spec,
it stacks the plates, puts each screw through its holes and writes every screw's interference
volume with every plate it joins (JSON at "output", STLs next to it). The reply is one JSON
line {"ok": true} or {"ok": false, "error": "..."}. Programs are checked (check_code) by the
caller before they get here; webapp/builder.py restarts this process if a job hangs or it dies.
"""
import contextlib
import json
import sys
import traceback


def _run_program(path, overrides=None):
    import cadquery as cq

    from candidates import FUNCTION_NAME

    with open(path, encoding="utf-8") as file:
        code = file.read()
    namespace = {"__name__": "candidate"}
    exec(compile(code, path, "exec"), namespace)
    result = namespace[FUNCTION_NAME](**(overrides or {}))
    return result if isinstance(result, cq.Workplane) else cq.Workplane("XY").add(result)


def build(job):
    import cadquery as cq

    if job.get("assembly") is not None:  # the adapter's assembly check: plates, screws, clashes
        assembly(job["assembly"], job["output"])
        return
    result = _run_program(job["code"], job.get("overrides"))
    if job.get("compare_to"):  # a completion: what it adds to and removes from another program's part
        compare(result, _run_program(job["compare_to"]), job)
        return
    if job["output"].endswith(".profile.json"):  # the top face for drawings, DXF and the 1:1 template
        with open(job["output"], "w", encoding="utf-8") as file:
            json.dump(profile(result), file)
        return
    if job["output"].endswith(".npy"):  # top-view silhouette instead of a CAD file
        import numpy as np

        from render_silhouette import render_top_silhouette

        np.save(job["output"], render_top_silhouette(result, float(job["mm_per_pixel"])) > 0)
    else:
        cq.exporters.export(result, job["output"])
    if job.get("features"):
        with open(job["features"], "w", encoding="utf-8") as file:
            json.dump(features(result), file)


def compare(result, base, job):
    """Write the material `result` adds to `base` as an STL (job["output"]) and the volumes as JSON (job["features"])."""
    import cadquery as cq

    added, removed = result.cut(base), base.cut(result)
    volume = lambda part: sum(solid.Volume() for solid in part.solids().vals())  # noqa: E731
    report = {"base_volume_mm3": round(volume(base), 2), "result_volume_mm3": round(volume(result), 2),
              "added_volume_mm3": round(volume(added), 2), "removed_volume_mm3": round(volume(removed), 2)}
    if report["added_volume_mm3"] > 1e-3:
        cq.exporters.export(added, job["output"])
    if job.get("removed_output") and report["removed_volume_mm3"] > 1e-3:
        cq.exporters.export(removed, job["removed_output"])
    with open(job["features"], "w", encoding="utf-8") as file:
        json.dump(report, file)


def assembly(spec, report_path):
    """Stack the spec's plates, put each screw through the plates it joins, and report every
    screw's interference volume per plate. Writes plate_<name>.stl, screw_<id>.stl and, for a
    screw that overlaps material, clash_<id>_<plate>.stl next to the report (all in the stack's
    coordinates: plates face to face from Z = 0 up, screws at their fixed positions)."""
    import cadquery as cq
    from pathlib import Path

    import partkit as pk

    folder = Path(report_path).parent
    folder.mkdir(parents=True, exist_ok=True)
    plate_mid = {plate["name"]: plate["z0"] + plate["thickness"] / 2 for plate in spec["plates"]}
    plates = {}
    for plate in spec["plates"]:
        part = pk.outline_from_points(plate["outline"], plate["thickness"]).translate((0, 0, plate["z0"]))
        for hole in plate["holes"]:
            if "circle" in hole:
                (x, y, d) = hole["circle"]
                part = pk.cut_circle(part, (x, y), d)
            elif "slot" in hole:
                (x, y, length, width, angle) = hole["slot"]
                part = pk.cut_slot(part, (x, y), length, width, angle)
            else:
                part = pk.cut_polygon(part, hole["polygon"])
        plates[plate["name"]] = part
        cq.exporters.export(part, str(folder / f"plate_{plate['name']}.stl"))
    screws = []
    for screw in spec["screws"]:
        x, y, d, z0, z1 = (screw[key] for key in ("x", "y", "d", "z0", "z1"))
        solid = cq.Workplane("XY", origin=(x, y, z0)).circle(d / 2).extrude(z1 - z0)
        cq.exporters.export(solid, str(folder / f"screw_{screw['id']}.stl"))
        interference, penetration = {}, {}
        for name in plates:  # every screw with every plate (a screw only reaches the plates it joins)
            overlap = solid.intersect(plates[name])
            clash = overlap.solids().vals()
            amount = sum(part.Volume() for part in clash)
            interference[name] = amount
            depth = 0.0
            if amount > 1e-9:
                depth = clash_depth(clash, (x, y), screw["shift"], plate_mid[name])
                cq.exporters.export(overlap, str(folder / f"clash_{screw['id']}_{name}.stl"))
            penetration[name] = depth
        screws.append({"id": screw["id"], "size": screw["size"], "pattern": screw["pattern"],
                       "x": x, "y": y, "d": d, "z0": z0, "z1": z1,
                       "interference_mm3": {name: round(value, 4) for name, value in interference.items()},
                       "penetration_mm": {name: round(value, 4) for name, value in penetration.items()},
                       "total_mm3": round(sum(interference.values()), 4)})
    with open(report_path, "w", encoding="utf-8") as file:
        json.dump({"screws": screws, "plates": [
            {"name": p["name"], "label": p["label"], "thickness": p["thickness"], "z0": p["z0"]}
            for p in spec["plates"]]}, file)


def clash_depth(solids, center_xy, shift_xy, z):
    """Penetration depth (mm): the length of the clash inside the line through the screw center
    along the shift direction. The line's section with the clash solids gives entry/exit vertices;
    sorted along the line and paired in order, their spans add up (a lone tangent graze has none)."""
    import cadquery as cq
    from OCP.BRep import BRep_Tool
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    direction = cq.Vector(shift_xy[0], shift_xy[1], 0).normalized()
    middle = cq.Vector(center_xy[0], center_xy[1], z)
    edge = cq.Edge.makeLine(middle - direction * 1000, middle + direction * 1000)
    params = []
    for solid in solids:
        section = BRepAlgoAPI_Section(edge.wrapped, solid.wrapped)
        section.Build()
        if not section.IsDone():
            continue
        explorer = TopExp_Explorer(section.Shape(), TopAbs_VERTEX)
        while explorer.More():
            point = BRep_Tool.Pnt_s(TopoDS.Vertex_s(explorer.Current()))
            params.append((point.X() - middle.x) * direction.x + (point.Y() - middle.y) * direction.y)
            explorer.Next()
    params.sort()
    if len(params) % 2:
        params = params[:-1]
    return sum(b - a for a, b in zip(params[::2], params[1::2]))


def profile(result):
    """The part's top face in mm: outline and holes (circles as center and diameter, other shapes as closed
    polylines, 0.01 mm accurate), the outline's circular arcs (center and diameter, so a hole opened into the
    edge can be told by its exact center), the bounding box and the thickness. Prismatic parts only."""
    import cv2
    import numpy as np

    solid = result.findSolid()
    top = max(vertex.Z for vertex in solid.Vertices())
    faces = [f for f in solid.Faces() if f.normalAt().z > 0.99 and abs(f.Center().z - top) < 1e-3]
    face = max(faces, key=lambda f: f.Area())

    def polyline(wire):
        # Edge by edge in the wire's order: a straight edge adds its exact start corner, a curved edge its
        # points every 0.25 mm; then collinear points are dropped (0.01 mm).
        import cadquery as cq
        from OCP.BRepTools import BRepTools_WireExplorer

        points = []
        explorer = BRepTools_WireExplorer(wire.wrapped)
        while explorer.More():
            edge = cq.Edge(explorer.Current())
            start = cq.Vertex(explorer.CurrentVertex()).toTuple()[:2]
            if edge.geomType() == "LINE":
                points.append(start)
            else:
                count = max(8, int(edge.Length() / 0.25))
                samples = [(p.x, p.y) for p in edge.positions(np.linspace(0, 1, count, endpoint=False))]
                if np.hypot(samples[0][0] - start[0], samples[0][1] - start[1]) > 1e-3:  # the edge runs backwards
                    samples = [(p.x, p.y) for p in edge.positions(np.linspace(1, 0, count, endpoint=False))]
                points.extend(samples)
            explorer.Next()
        simple = cv2.approxPolyDP(np.array(points, np.float32).reshape(-1, 1, 2), 0.01, True).reshape(-1, 2)
        return [[round(float(x), 3), round(float(y), 3)] for x, y in simple]

    holes = []
    for wire in face.innerWires():
        edges = wire.Edges()
        if len(edges) == 1 and edges[0].geomType() == "CIRCLE":
            center = edges[0].arcCenter()
            holes.append({"type": "circle", "center": [round(center.x, 3), round(center.y, 3)],
                          "diameter": round(2 * edges[0].radius(), 3)})
        else:
            holes.append({"type": "polyline", "points": polyline(wire)})
    arcs = [{"center": [round(edge.arcCenter().x, 3), round(edge.arcCenter().y, 3)], "diameter": round(2 * edge.radius(), 3)}
            for edge in face.outerWire().Edges() if edge.geomType() == "CIRCLE"]
    box = solid.BoundingBox()
    bottom = min(vertex.Z for vertex in solid.Vertices())
    return {"outline": polyline(face.outerWire()), "outline_arcs": arcs, "holes": holes,
            "thickness": round(top - bottom, 3), "box": [round(v, 3) for v in (box.xmin, box.ymin, box.xmax, box.ymax)],
            "solid_count": len(result.solids().vals())}


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
            "holes": holes, "hole_kinds": hole_kinds(result, top), "solids": len(result.solids().vals())}


def _polyline_is_slot(wire, tolerance_mm=0.05):
    """Whether a hole made only of straight edges traces a slot (two half circles joined by two straight
    sides) within tolerance_mm: a matching part cuts the original's slot as its 0.01 mm profile points, so
    it arrives as many short lines. Naming only; the geometry is not touched."""
    import numpy as np

    points = np.array([(v.X, v.Y) for v in wire.Vertices()])
    if len(points) < 8:
        return False
    centered = points - points.mean(axis=0)
    axis = np.linalg.svd(centered, full_matrices=False)[2][0]
    along, across = centered @ axis, centered @ np.array([-axis[1], axis[0]])
    along -= (along.max() + along.min()) / 2
    across -= (across.max() + across.min()) / 2
    radius = (across.max() - across.min()) / 2
    half = (along.max() - along.min()) / 2 - radius  # half length of the straight sides
    if radius <= 0 or half <= 0.05 * radius:
        return False
    distance = np.hypot(along - np.clip(along, -half, half), across)
    return bool(np.all(np.abs(distance - radius) <= max(tolerance_mm, 0.01 * radius)))


def hole_kinds(result, top):
    """How many holes of each shape the top faces have, for naming the count ("1 round hole + 1 slot"):
    a single circle is round, two arcs joined by two lines a slot (or straight edges tracing one, as in a
    matching part), four lines a rectangular hole, anything else shaped. Read from the built model's
    edges; no measurement involved."""
    kinds = {"round": 0, "slot": 0, "rectangular": 0, "shaped": 0}
    for solid in result.solids().vals():
        for face in solid.Faces():
            if face.normalAt().z < 0.99 or abs(face.Center().z - top) > 1e-3:
                continue
            for wire in face.innerWires():
                types = sorted(edge.geomType() for edge in wire.Edges())
                if types == ["CIRCLE"]:
                    kinds["round"] += 1
                elif types == ["CIRCLE", "CIRCLE", "LINE", "LINE"]:
                    kinds["slot"] += 1
                elif types == ["LINE"] * 4:
                    kinds["rectangular"] += 1
                elif set(types) == {"LINE"} and _polyline_is_slot(wire):
                    kinds["slot"] += 1
                else:
                    kinds["shaped"] += 1
    return kinds


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
