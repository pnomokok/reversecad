"""Recorded adapter outlines: a sample may ship the Muse Spark Open adapter outline search of its run
(7_adapter_recorded/outline.json + outline.py, packed by make_sample.py). Without keys (always in the
demo) the adapter endpoint serves that recorded program instead of the deterministic fallback, but only
when the request rebuilds exactly the recorded inputs: the same pattern A holes, placed pattern B holes,
thickness and edge margin (the pattern's label may differ, e.g. a preset instead of the spoken pattern).
Nothing is called and nothing is recomputed; any other input still gets the fallback.
"""
import json
from pathlib import Path

FOLDER = "7_adapter_recorded"
SOURCE_LABEL = "Muse Spark Open · recorded"


def _canonical(value):
    """Numbers rounded to 0.001 mm, so a rebuilt profile compares equal to the recorded one."""
    if isinstance(value, float):
        return round(value, 3)
    if isinstance(value, dict):
        return {k: _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def _holes(holes):
    return sorted(json.dumps(_canonical(h), sort_keys=True) for h in holes)


def find(run_folder, holes_a, holes_b, thickness, margin_default):
    """(program source, recorded meta) when run_folder ships a recorded outline for exactly these inputs, else None."""
    folder = Path(run_folder) / FOLDER
    meta_path, program = folder / "outline.json", folder / "outline.py"
    if not (meta_path.exists() and program.exists()):
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    same = (_holes(meta["holes_a"]) == _holes(holes_a)
            and _holes(meta["placement"]["holes_b"]) == _holes(holes_b)
            and abs(float(meta["thickness"]) - float(thickness)) < 1e-6
            and abs(float(meta["margin_default"]) - float(margin_default)) < 1e-6)
    return (program.read_text(encoding="utf-8"), meta) if same else None
