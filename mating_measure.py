"""Pattern B measured from a photo of the mating part.

The mating photo goes through the existing pipeline unchanged (SAM 3.1 card + click mask,
the frozen scale rule and hole finding); this module only reads the saved measurement table
and turns its holes into a pattern: centers relative to the holes' own centroid, measured
diameters (for non-round holes the equal-area diameter the table reports). Validation is the
same deterministic check the typed patterns go through; anything unusable is refused in plain
words, never guessed.
"""
import adapter_pattern

#: What the hole list is summarized with: the computed summary plus where it came from.
SOURCE_SUFFIX = "measured from photo · SAM 3.1"
#: What the pattern itself is labeled with, so the overlay legend reads "Pattern B · ... from photo".
LABEL_SUFFIX = "from photo"


def pattern_from_table(table):
    """(result, None) with pattern B from a measurement table, or (None, a message for the user).

    result is {"pattern", "summary", "outline_mm", "outline_polygon_mm"}: the validated pattern
    (holes centroid-relative, diameters measured), the one-line summary, and the mating part's
    measured outline for the assembly check.
    """
    holes = (table or {}).get("holes") or []
    if not holes:
        return None, ("No holes were found in the mating part's photo, so there is no hole pattern "
                      "to use. The holes must show the background through them; blind holes and "
                      "anything covered (stickers, clear domes) cannot be measured from above.")
    centroid = [sum(h["center_from_part_center_mm"][axis] for h in holes) / len(holes) for axis in (0, 1)]
    measured = [{"x": round(h["center_from_part_center_mm"][0] - centroid[0], 3),
                 "y": round(h["center_from_part_center_mm"][1] - centroid[1], 3),
                 "d": h["diameter_mm"]} for h in holes]
    summary = adapter_pattern.summarize_pattern({"holes": measured})
    pattern, error = adapter_pattern.validate_pattern({"holes": measured, "label": summary})
    if pattern is None:
        return None, f"The mating part's holes can't be used as a hole pattern: {error}."
    pattern["label"] = f"{summary} · {LABEL_SUFFIX}"
    outline = (table.get("outline") or {})
    return {"pattern": pattern, "summary": f"{summary} · {SOURCE_SUFFIX}",
            "outline_mm": [outline.get("length_mm"), outline.get("width_mm")],
            "outline_polygon_mm": outline.get("polygon_mm")}, None
