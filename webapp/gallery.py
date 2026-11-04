"""Parts gallery: every finished run as a card (GET /api/parts).

Samples are always listed. Local template-scene runs too, unless their folder holds
a private.txt marker. A local live-* run (an uploaded photo) is shown only when its
folder holds a public.txt marker: privacy is opt-in. private.txt always wins over
public.txt. In demo mode this is samples-only, because the server narrows
replay.SOURCES to samples/. New run folders show up with no code changes. Only
values saved in the run are shown; unfinished runs (no result program) are
skipped, never guessed.
"""
import json
from pathlib import Path

from webapp import replay

PRIVATE_MARKER = "private.txt"  # a run folder holding this file stays out of the gallery
PUBLIC_MARKER = "public.txt"  # a local live-* run needs this file to be shown


def is_private(folder):
    """A run is private when its folder carries the marker (see module docstring)."""
    return (Path(folder) / PRIVATE_MARKER).exists()


def is_public(folder):
    """A run is opted in when its folder carries the public marker (live-* runs only)."""
    return (Path(folder) / PUBLIC_MARKER).exists()


def _is_sample(folder):
    """A run folder inside samples/ (committed examples, always listed)."""
    return Path(folder).resolve().parent == replay.SAMPLES_DIR.resolve()


def source_label(source):
    """The saved result source as the short card label, or None when unknown."""
    if not source:
        return None
    if source == replay.COMPLETION_SOURCE:
        return "Completion applied"
    if source == "candidate":
        return "Winner"
    if source.startswith("repair"):
        return "Muse Wonder repair"
    if source.startswith("fallback"):
        return "Fallback"
    return None


def card(name):
    """One gallery card from the run's saved files, or None when it is not finished."""
    try:
        folder = replay.run_dir(name)
        if is_private(folder):
            return None  # private wins over public
        if name.startswith("live-") and not _is_sample(folder) and not is_public(folder):
            return None  # a local upload stays out unless opted in with public.txt
        table = json.loads((folder / "3_measurements.json").read_text(encoding="utf-8"))["table"]
        # result_program raises when there is no result, so a missing source means a plain
        # winner (the same default as done_event).
        label = source_label(replay.result_program(name)[1] or "candidate")
        if label is None:
            return None
        outline = table["outline"]
        # Live runs are uploaded photos; template scenes and samples are rendered, except a
        # recorded live run in samples/, which says so. (One older exception:
        # live-20261028-013118-d23896, a synthetic render uploaded as a test.)
        kind = replay.run_kind(name)  # the same source as the run chip
        if kind == "Real photo" and _is_sample(folder):
            kind = "Real photo · recorded live run"
        return {"name": name, "title": replay.display_name(name), "length_mm": outline["length_mm"], "width_mm": outline["width_mm"],
                "hole_count": len(table["holes"]), "source": label, "kind": kind}
    except (FileNotFoundError, KeyError, ValueError, TypeError, OSError):
        return None  # unfinished or unreadable: no card, never a guess


def gallery_runs():
    """Cards for every finished, non-private run (folder scan, sorted by name)."""
    cards = []
    for name in replay.list_runs():
        entry = card(name)
        if entry is not None:
            cards.append(entry)
    return cards
