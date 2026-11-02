"""Assembly check for an adapter plate: do the screws fit through the stack?

The stack is the original part, the adapter plate and the mating part (or a stand-in plate when
pattern B came from a preset, text or voice). Every plate is rebuilt from its built top-face
profile through a baseline table (baseline_cad): round holes stay exact circles, outlines and
shaped holes arrive as the profile's 0.01 mm points. Screws are fixed cylinders at the adapter's
hole centers - they are rigid, so a screw either passes every plate it joins or it is blocked.

Two hole styles: Exact (holes as built) and Slotted (every round hole of pattern A and pattern B,
on every plate that carries it, becomes a slot along its pattern's long axis, 2 x SHIFT_MM longer
than the hole's diameter). Two error cases: As measured (holes where the models put them) and
With measured error (each pattern's own hole spacing grows by SHIFT_MM: every hole moves SHIFT_MM
/ 2 outward from its pattern's centroid along the long axis; the adapter stays nominal).

Why slots live on every plate, not just the adapter: with the error shift (0.64 mm per side) larger
than a screw's radial slack (e.g. 0.50 mm for M5 in a 6.0 mm hole), a slot in the middle plate alone
cannot save a fixed screw - the shifted round holes of the outer plates still overlap it. Slotting
the joint's holes everywhere is what lets the same fixed screws pass.

Pure geometry and bookkeeping only; the solids and the interference volumes are computed by the
build worker (its "assembly" job), which is the only place CadQuery is touched.
"""
import math

import adapter_pattern
import adapter_place
import baseline_cad

#: Largest hole-spacing error measured on a real photo: reports/real_parts.md section 3,
#: the parallel shot's bottom punch pair reads 78.72 mm against the 80 mm punch distance.
SHIFT_MM = 1.28

#: Nominal shank diameters (mm) for the metric screw sizes the adapter knows.
SHANK_DIAMETER_MM = {"M3": 3.0, "M4": 4.0, "M5": 5.0, "M6": 6.0}

#: A screw passes when its total interference volume stays below this (mm^3); a clean pass
#: through concentric holes intersects nothing, so this only absorbs float noise.
INTERFERENCE_EPS_MM3 = 1e-6

#: Screw sticks out past the outer faces by this much (mm), so its ends stay visible.
SCREW_PROTRUDE_MM = 1.0

#: The stand-in plate (no mating photo) reaches past pattern B's holes by this much on every side.
STAND_IN_MARGIN_MM = 2.0

STAND_IN_LABEL = "stand-in plate"
MATING_LABEL = "measured mating part"

HOLE_STYLES = ("exact", "slotted")
ERROR_CASES = ("as_measured", "with_error")


def screw_for_diameter(diameter_mm):
    """Largest metric size whose ISO 273 medium clearance fits the hole, or None when none fits."""
    fitting = [size for size, clearance in adapter_pattern.ISO_273_MEDIUM.items() if clearance <= diameter_mm]
    return max(fitting, key=lambda size: adapter_pattern.ISO_273_MEDIUM[size]) if fitting else None


def pattern_long_axis(centers):
    """A pattern's long axis in degrees (0 = X, 90 = Y): the long side of its holes' bounding box.

    A single hole, or an exactly square layout, has no long side; X wins ties deterministically.
    """
    xs = [c[0] for c in centers]
    ys = [c[1] for c in centers]
    return 0.0 if max(xs) - min(xs) >= max(ys) - min(ys) else 90.0


def error_shifted_centers(centers, axis_deg):
    """Hole centers with the measured error: every hole SHIFT_MM / 2 outward from the centroid
    along the pattern's long axis, so the spacing along that axis grows by SHIFT_MM."""
    cx = sum(c[0] for c in centers) / len(centers)
    cy = sum(c[1] for c in centers) / len(centers)
    unit = (1.0, 0.0) if axis_deg == 0.0 else (0.0, 1.0)
    moved = []
    for x, y in centers:
        side = (x - cx) * unit[0] + (y - cy) * unit[1]
        step = SHIFT_MM / 2 * (1.0 if side >= 0 else -1.0)
        moved.append([round(x + unit[0] * step, 3), round(y + unit[1] * step, 3)])
    return moved


def slot_polygon(center, length_mm, width_mm, angle_deg, steps=24):
    """A slot's boundary as [(x, y)]: a capsule, length end to end, sampled every few degrees."""
    straight = (length_mm - width_mm) / 2  # center to each end-arc center along the axis
    angle = math.radians(angle_deg)
    ux, uy = math.cos(angle), math.sin(angle)
    points = []
    for end, start in ((1.0, -90.0), (-1.0, 90.0)):
        ex, ey = center[0] + ux * straight * end, center[1] + uy * straight * end
        for i in range(steps // 2 + 1):
            arc = math.radians(start + 180.0 * i / (steps // 2))
            # the arc's own frame is turned with the slot
            lx, ly = math.cos(arc) * width_mm / 2, math.sin(arc) * width_mm / 2
            points.append((round(ex + lx * ux - ly * uy, 4), round(ey + lx * uy + ly * ux, 4)))
    return points


def slot_wall_form(center, diameter_mm, axis_deg):
    """A round hole as a slot in wall form: {"polygon"} of width = diameter, length = diameter +
    2 x SHIFT_MM along the axis."""
    return {"polygon": slot_polygon(center, diameter_mm + 2 * SHIFT_MM, diameter_mm, axis_deg)}


def check_slotted_walls(outline, holes_a, holes_b):
    """(slots, None) when every round hole can become a slot, else (None, which check breaks).

    holes_a are the adapter's built pattern-A holes ({"circle": (x, y, d)} or {"polygon": points}),
    holes_b the placed pattern-B circles; slots run along each pattern's own long axis. The existing
    checks must still pass: every A-A, A-B and B-B wall at MIN_WALL_MM and every slotted hole's
    margin at MIN_WALL_MM, so no holes merge and none break out. (The design margin
    cannot hold: slots reach SHIFT_MM past the round holes the outline was drawn for, so
    requiring it would refuse every outline.) slots is {"a": [...], "b": [...]} in the adapter's coordinates, each a
    {"center", "width", "length", "angle"} slot or a {"polygon"} left as it was.
    """
    specs = {"a": _slot_specs(holes_a, "a"), "b": _slot_specs(
        [{"circle": (h["x"], h["y"], h["d"])} for h in holes_b], "b")}
    walls = {}
    for tag in ("a", "b"):
        forms = [spec["form"] for spec in specs[tag]]
        pairs = [adapter_place.hole_wall(x, y) for i, x in enumerate(forms) for y in forms[i + 1:]]
        walls[tag * 2] = min(pairs) if pairs else None
    cross = [adapter_place.hole_wall(a["form"], b["form"]) for a in specs["a"] for b in specs["b"]]
    walls["ab"] = min(cross) if cross else None
    for name, value in walls.items():
        if value is not None and value < adapter_place.MIN_WALL_MM:
            pair = {"aa": "pattern A", "bb": "pattern B", "ab": "A–B"}[name]
            return None, (f"Slotted breaks the {pair} wall ({value:.1f} mm "
                          f"< {adapter_place.MIN_WALL_MM:.1f} mm) — keeping Exact")
    for tag in ("a", "b"):
        for spec in specs[tag]:
            if "slot" not in spec:
                continue
            gap = adapter_place.hole_to_outline(spec["form"], outline)
            if gap < adapter_place.MIN_WALL_MM:
                return None, (f"Slotted breaks hole {spec['id']}'s edge margin ({gap:.1f} mm "
                              f"< {adapter_place.MIN_WALL_MM:.1f} mm) — keeping Exact")
    return specs, None


def _slot_specs(holes, tag):
    """Each hole as {"id", "form", "slot"?}: rounds become slots along the pattern's long axis."""
    centers = [adapter_place.hole_center(hole) for hole in holes]
    axis = pattern_long_axis(centers) if centers else 0.0
    specs = []
    order = sorted(range(len(holes)), key=lambda i: (centers[i][0], centers[i][1]))
    for position, i in enumerate(order, 1):
        if "circle" in holes[i]:
            x, y, diameter = holes[i]["circle"]
            specs.append({"id": f"{tag.upper()}{position}", "center": [x, y], "width": diameter,
                          "length": round(diameter + 2 * SHIFT_MM, 3), "angle": axis,
                          "form": slot_wall_form((x, y), diameter, axis), "slot": True})
        else:
            specs.append({"id": f"{tag.upper()}{position}", "polygon": holes[i]["polygon"],
                          "form": holes[i]})
    return specs


def placement_transform(placement, pattern):
    """(dx, dy, rotated90): the rigid motion the placement applied to pattern B's holes.

    Read from the placement record when it carries the transform (newer searches); otherwise
    derived by matching the pattern against the placed holes under 0 and 90 degrees (the only
    rotations placement tries, 0 preferred). Raises ValueError when neither matches.
    """
    stored = (placement or {}).get("transform")
    if stored is not None:
        return stored["dx"], stored["dy"], stored["rotated90"]
    placed = [(h["x"], h["y"]) for h in placement["holes_b"]]
    plain = [(h["x"], h["y"]) for h in pattern["holes"]]
    if len(placed) != len(plain):
        raise ValueError("pattern B does not match its placed holes under 0 or 90 degrees")
    for rotated in (False, True):
        moved = [(-y, x) if rotated else (x, y) for x, y in plain]
        dx = sum(p[0] - m[0] for p, m in zip(placed, moved)) / len(placed)
        dy = sum(p[1] - m[1] for p, m in zip(placed, moved)) / len(placed)
        if all(math.dist(p, (m[0] + dx, m[1] + dy)) < 0.01 for p, m in zip(placed, moved)):
            return round(dx, 3), round(dy, 3), rotated
    raise ValueError("pattern B does not match its placed holes under 0 or 90 degrees")


def transform_point(point, dx, dy, rotated90):
    """A mating-frame point into adapter coordinates."""
    x, y = (-point[1], point[0]) if rotated90 else (point[0], point[1])
    return [round(x + dx, 3), round(y + dy, 3)]


def mating_table(measured_table, mating_json, placement, pattern, thickness_mm):
    """A baseline table for the mating part in adapter coordinates: the measured outline polygon
    and the measured holes (full records, so shaped holes survive), moved by the placement.

    measured_table is the mating run's 3_measurements.json table, mating_json its 4_mating.json.
    """
    table, mating = measured_table, mating_json
    dx, dy, rotated = placement_transform(placement, pattern)
    holes = []
    for hole in table["holes"]:
        record = {"shape": hole["shape"],
                  "center_from_part_center_mm": transform_point(hole["center_from_part_center_mm"], dx, dy, rotated),
                  "diameter_mm": hole["diameter_mm"]}
        if hole["shape"] in ("rectangle", "slot", "ellipse", "polygon"):
            record.update({"length_mm": hole["length_mm"], "width_mm": hole["width_mm"],
                           "angle_deg": round((hole["angle_deg"] + (90.0 if rotated else 0.0)) % 180, 1)})
        if hole["shape"] == "polygon":
            record["polygon_mm"] = [transform_point(p, dx, dy, rotated) for p in hole["polygon_mm"]]
        holes.append(record)
    return {"outline": {"polygon_mm": [transform_point(p, dx, dy, rotated)
                                      for p in mating["outline_polygon_mm"]],
                        "length_mm": mating["outline_mm"][0], "width_mm": mating["outline_mm"][1]},
            "holes": holes}, thickness_mm


def stand_in_table(holes_b, thickness_mm, margin_mm=STAND_IN_MARGIN_MM):
    """A baseline table for the stand-in plate: a plain rectangle around the placed pattern B."""
    x0 = min(h["x"] - h["d"] / 2 for h in holes_b) - margin_mm
    x1 = max(h["x"] + h["d"] / 2 for h in holes_b) + margin_mm
    y0 = min(h["y"] - h["d"] / 2 for h in holes_b) - margin_mm
    y1 = max(h["y"] + h["d"] / 2 for h in holes_b) + margin_mm
    return {"outline": {"polygon_mm": [[round(x0, 3), round(y0, 3)], [round(x1, 3), round(y0, 3)],
                                          [round(x1, 3), round(y1, 3)], [round(x0, 3), round(y1, 3)]],
                        "length_mm": round(x1 - x0, 3), "width_mm": round(y1 - y0, 3)},
            "holes": [{"shape": "circle", "center_from_part_center_mm": [h["x"], h["y"]],
                       "diameter_mm": h["d"]} for h in holes_b]}, thickness_mm


def as_slot_record(center, diameter_mm, axis_deg):
    """A round hole as a slot record: width = diameter, length = diameter + 2 x SHIFT_MM."""
    return {"shape": "slot", "center_from_part_center_mm": [center[0], center[1]],
            "diameter_mm": diameter_mm, "length_mm": round(diameter_mm + 2 * SHIFT_MM, 3),
            "width_mm": diameter_mm, "angle_deg": axis_deg}


def profile_table(outline_points, holes):
    """A baseline table for a rebuilt plate: the outline points and holes in final coordinates,
    each {"circle": (x, y, d)}, {"slot": (x, y, length, width, angle_deg)} or {"polygon": points}."""
    table_holes = []
    for hole in holes:
        if "circle" in hole:
            x, y, diameter = hole["circle"]
            table_holes.append({"shape": "circle", "center_from_part_center_mm": [x, y],
                                "diameter_mm": diameter})
        elif "slot" in hole:
            x, y, length, width, angle = hole["slot"]
            table_holes.append({"shape": "slot", "center_from_part_center_mm": [x, y],
                                "diameter_mm": width, "length_mm": length, "width_mm": width,
                                "angle_deg": angle})
        else:
            table_holes.append({"shape": "polygon", "polygon_mm": [list(p) for p in hole["polygon"]]})
    return {"outline": {"polygon_mm": [list(p) for p in outline_points]}, "holes": table_holes}
