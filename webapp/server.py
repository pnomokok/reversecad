"""FastAPI back end for the ReverseCAD web app.

Serves the front end (webapp/static/) and a JSON API. Saved runs (outputs/e2e/<scene>/)
replay without calling any model; live mode (/api/live/...) runs the pipeline on an
uploaded photo and saves it as a run in the same format.

Run from the repository root:
    .venv\\Scripts\\python.exe -m uvicorn webapp.server:app --reload
then open http://127.0.0.1:8000
"""
import asyncio
import hashlib
import io
import json
import math
import os
import re
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import adapter_outline
import adapter_pattern
import adapter_place
import assembly_check
import baseline_cad
import drawing_export
import matching_part
import mating_measure
import voice_edit
from webapp import gallery, live, replay
from webapp.builder import Builder

load_dotenv()  # API keys from .env (never printed); live mode and repair need them

# Online demo (modal_app.py): only the saved samples, and nothing that needs an API key.
DEMO = os.getenv("REVERSECAD_DEMO") == "1"
if DEMO:
    replay.SOURCES = [replay.SAMPLES_DIR]


def _needs_keys():
    if DEMO:
        raise HTTPException(403, "this online demo replays saved examples only; live mode, repair and voice "
                                 "editing need API keys (run it locally, see the README)")

STATIC = Path(__file__).parent / "static"
MODEL_DIR = Path("outputs") / "web"  # temporary model files (git-ignored)
MATCHING_DIR = MODEL_DIR / "matching"  # generated matching programs, named by what they were made from
_ADAPTER_KEY_VERSION = 3  # bump when the adapter fallback or search changes (older cache files are orphaned)
_MATCHING_KEY_VERSION = 2  # same for cover/spacer programs
REPLAY_DELAY_S = 0.4  # pause between replayed candidate events
builder = Builder()  # one long-running build process (CadQuery loads once)


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=builder.warm_up, daemon=True).start()  # ready before the first slider move
    yield
    builder.close()  # stop the build process when the server stops


app = FastAPI(title="ReverseCAD", lifespan=lifespan)


@app.get("/api/config")
def config():
    """What this server can do: the online demo replays samples only; keys decide live mode and voice editing."""
    return {"demo": DEMO, "live": not DEMO and bool(os.getenv("MODEL_API_KEY") and os.getenv("BASETEN_API_KEY")),
            "voice": not DEMO and bool(os.getenv("BASETEN_API_KEY")),
            "speech": not DEMO and bool(os.getenv("BASETEN_API_KEY") and os.getenv("MODEL_API_KEY"))}


@app.get("/api/runs")
def runs():
    """Saved runs that can be replayed."""
    return {"runs": replay.list_runs()}


@app.get("/api/parts")
def parts():
    """Parts gallery: every finished, non-private run as a card (folder scan, no code per run)."""
    return {"parts": gallery.gallery_runs()}


@app.get("/api/runs/{name}/photo")
def run_photo(name: str):
    try:
        return FileResponse(replay.photo_path(name))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/info")
def run_info(name: str):
    """Screen 1: the saved click and photo size, without the slow mask decoding."""
    try:
        return replay.info(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/analysis")
def run_analysis(name: str):
    """Screens 1-2: click, card, part outline, holes and the measurement table."""
    try:
        return replay.analysis(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/candidates/stream")
async def candidate_stream(name: str, round: str | None = None):
    """Screen 3: candidates as server-sent events, one by one as they would arrive live, then 'done'.

    ?round=<folder> replays an older saved round of the run instead of the newest.
    """
    try:
        events = replay.candidate_events(name, round)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))

    async def stream():
        for event in events:
            await asyncio.sleep(REPLAY_DELAY_S)  # replay pace; live mode sends as candidates finish
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/runs/{name}/reference.png")
def run_reference(name: str):
    """The reference mask, shown dimmed behind each candidate silhouette."""
    try:
        return FileResponse(replay.reference_path(name))
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/candidates/{candidate}/silhouette.png")
def candidate_silhouette(name: str, candidate: int, round: str | None = None):
    try:
        return Response(replay.silhouette_png(name, candidate, round), media_type="image/png")
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/winner")
def run_winner(name: str):
    """Screen 4: the result program and its named numeric parameters."""
    try:
        return replay.winner(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


def _checked(values, allowed):
    """Posted parameter values, checked: only the program's own numeric parameters."""
    overrides = {}
    for key, value in (values or {}).items():
        if key not in allowed or not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(400, f"unknown or non-numeric parameter: {key}")
        overrides[key] = float(value)
    return overrides


def _result_names(name):
    """The names of the run's result program's parameters."""
    try:
        return {p["name"] for p in replay.winner(name)["parameters"]}
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


async def _parameters(name, request):
    """The posted {"parameters": {...}}, checked against the run's result program."""
    return _checked((await request.json()).get("parameters"), _result_names(name))


async def _matching(name, kind, base):
    """(program path, the original's top-face profile) for a matching part of the run's result built
    with the `base` values.

    The request carries everything needed, so no server keeps a session; the files only save rebuilding
    the original on every slider move. Their name is a hash of what they were made from.
    """
    if kind not in matching_part.KINDS:
        raise HTTPException(400, f"a matching part is one of: {', '.join(matching_part.KINDS)}")
    overrides = _checked(base, _result_names(name))
    original, _ = replay.result_program(name)
    made_from = json.dumps([kind, _MATCHING_KEY_VERSION, original.read_text(encoding="utf-8"), overrides],
                           sort_keys=True)
    key = hashlib.sha256(made_from.encode("utf-8")).hexdigest()[:24]
    program, profile_path = MATCHING_DIR / f"{key}.py", MATCHING_DIR / f"{key}.json"
    if not program.exists():
        profile = await _profile(original, overrides)
        MATCHING_DIR.mkdir(parents=True, exist_ok=True)
        # Each file appears whole: another request for the same part may be reading it.
        for path, text in ((profile_path, json.dumps(profile)),
                           (program, matching_part.matching_source(profile, kind, f"{name}_{kind}.py"))):
            temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(text, encoding="utf-8")
            temporary.replace(path)
    return program, json.loads(profile_path.read_text(encoding="utf-8"))


async def _adapter_key(name, body):
    """(cache key, pattern, overrides, original program, outline mode) for an adapter request."""
    pattern, error = adapter_pattern.validate_pattern((body or {}).get("pattern"))
    if pattern is None:
        raise HTTPException(422, f"pattern B is not usable: {error}")
    mode = (body or {}).get("outline", "auto")
    if mode not in ("auto", "fallback"):
        raise HTTPException(400, "outline must be auto or fallback")
    overrides = _checked((body or {}).get("base"), _result_names(name))
    original, _ = replay.result_program(name)
    made_from = json.dumps(["adapter", _ADAPTER_KEY_VERSION, original.read_text(encoding="utf-8"), overrides,
                            pattern, mode], sort_keys=True)
    return hashlib.sha256(made_from.encode("utf-8")).hexdigest()[:24], pattern, overrides, original, mode


def _adapter_build(path):
    """(profile, error) for an adapter candidate file, in the long-running build process."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{uuid.uuid4().hex}.profile.json").resolve()
    error = builder.build(path, output, {})
    if error:
        return None, error
    profile = json.loads(output.read_text(encoding="utf-8"))
    output.unlink()
    return profile, None


async def _target(name, request, match):
    """What a model, drawing or download request builds: (program path, overrides, name for its files).

    Without `match`, the run's result. With it ("cover", "spacer"), the matching part of the result built
    with the posted "base" values; "parameters" are then the matching program's own. "adapter" loads the
    searched outline for the posted base/pattern/outline (404 when no search ran for these inputs yet).
    """
    if match is None:
        overrides = await _parameters(name, request)
        return replay.result_program(name)[0], overrides, name
    body = await request.json()
    if match == "adapter":
        key, _, _, _, _ = await _adapter_key(name, body)
        style = body.get("hole_style", "exact")
        if style not in assembly_check.HOLE_STYLES:
            raise HTTPException(400, f"hole_style must be one of: {', '.join(assembly_check.HOLE_STYLES)}")
        program = MATCHING_DIR / (f"{key}.py" if style == "exact" else f"slotted_{key}.py")
        if not program.exists():
            hint = ("run the outline search first" if style == "exact"
                    else "switch the hole style to Slotted first")
            raise HTTPException(404, f"no adapter outline for these inputs yet ({hint})")
        allowed = {p["name"] for p in matching_part.slider_parameters(program.read_text(encoding="utf-8"))}
        return program, _checked(body.get("parameters"), allowed), f"{name}_adapter"
    program, _ = await _matching(name, match, body.get("base"))
    allowed = {p["name"] for p in matching_part.slider_parameters(program.read_text(encoding="utf-8"))}
    return program, _checked(body.get("parameters"), allowed), f"{name}_{match}"


async def _export(program, overrides, suffix, with_features=False):
    """Build a program with overrides into a .stl or .step file; return its bytes
    (and, with_features, the model's bounding box and top-face holes)."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{uuid.uuid4().hex}{suffix}").resolve()
    features_path = output.with_suffix(".json") if with_features else None
    error = await asyncio.to_thread(builder.build, program, output, overrides, None, features_path)
    if error:
        raise HTTPException(422, f"the program did not build with these values: {error.splitlines()[-1]}")
    data = output.read_bytes()
    output.unlink()
    if not with_features:
        return data
    features = features_path.read_text(encoding="utf-8")
    features_path.unlink()
    return data, features


@app.post("/api/runs/{name}/model")
async def build_model(name: str, request: Request, match: str | None = None):
    """Screen 4: build with the posted parameter values; binary STL for the viewer.

    Body: {"parameters": {"name": value, ...}}; only the program's own numeric parameters are accepted.
    ?match=cover|spacer|adapter builds a matching part instead (see _target).
    The X-Model-Features header carries the model's bounding box and top-face holes (JSON, mm).
    """
    program, overrides, _ = await _target(name, request, match)
    data, features = await _export(program, overrides, ".stl", with_features=True)
    return Response(data, media_type="model/stl", headers={"X-Model-Features": features})


def _matching_info(name, kind, program=None):
    """How a matching part is named on screen and in its files."""
    label = f"{name}_{kind}"
    titles = {**matching_part.KINDS, "adapter": "Adapter plate"}
    if kind == "adapter":  # which outline was used: the search winner, a repair, or the fallback
        meta = json.loads(Path(program).with_suffix(".json").read_text(encoding="utf-8"))
        source = f"Outline: {meta['outline_source']}"
    else:
        source = "built part, no model"
    return {"name": label, "program": f"{label}.py", "kind": kind, "title": titles[kind],
            "source": source}


@app.post("/api/runs/{name}/matching/{kind}")
async def matching_program(name: str, kind: str, request: Request):
    """A matching part of the result built with {"base": {...}}: its program and named parameters."""
    program, _ = await _matching(name, kind, (await request.json()).get("base"))
    return {**_matching_info(name, kind),
            "parameters": matching_part.slider_parameters(program.read_text(encoding="utf-8"))}


@app.post("/api/runs/{name}/matching/adapter/check")
async def adapter_check(name: str, request: Request):
    """The original's and the adapter's top faces as built: pattern A alignment, pattern B, margins.

    Body: {"base", "pattern", "outline", "parameters"}. Needs a searched outline (404 otherwise).
    Registered before /matching/{kind}/check, which would also match this path.
    """
    program, overrides, _ = await _target(name, request, "adapter")
    meta = json.loads(program.with_suffix(".json").read_text(encoding="utf-8"))
    style = (await request.json()).get("hole_style", "exact")
    _, original = await _matching(name, "cover", (await request.json()).get("base"))
    matching = await _profile(program, overrides)
    margins = [adapter_place.hole_to_outline(adapter_place.profile_hole(h), matching["outline"])
               for h in matching["holes"]]
    holes_b = meta["placement"]["holes_b"]
    holes_a = None
    if style == "slotted":  # the dashed overlays follow the slots, not the round holes
        axis = assembly_check.pattern_long_axis([[h["x"], h["y"]] for h in holes_b])
        holes_b = [{**h, "length": round(h["d"] + 2 * assembly_check.SHIFT_MM, 3),
                    "width": h["d"], "angle": axis} for h in holes_b]
        round_a = [h for h in original["holes"] if h["type"] == "circle"]
        if round_a:  # pattern A's slots, centered on the built adapter's A holes (closest pairs first)
            axis_a = assembly_check.pattern_long_axis([h["center"] for h in round_a])
            built_a = [t for t in _tagged_adapter_holes(matching["holes"], meta["placement"]["holes_b"])
                       if t["tag"] == "A"]
            pairs = sorted((math.dist(h["center"], t["center"]), i, j)
                           for i, h in enumerate(round_a) for j, t in enumerate(built_a))
            used_h, used_t, holes_a = set(), set(), []
            for _, i, j in pairs:
                if i in used_h or j in used_t:
                    continue
                used_h.add(i)
                used_t.add(j)
                holes_a.append({"x": built_a[j]["center"][0], "y": built_a[j]["center"][1],
                                "length": round(round_a[i]["diameter"] + 2 * assembly_check.SHIFT_MM, 3),
                                "width": round_a[i]["diameter"], "angle": axis_a})
    return {"original": original, "matching": matching,
            "alignment": matching_part.hole_alignment(original, matching),
            "holes_b": holes_b, "label_b": meta["pattern"]["label"], "holes_a": holes_a,
            "min_margin_mm": round(min(margins), 3) if margins else None,
            "outline_source": meta["outline_source"]}


@app.post("/api/runs/{name}/matching/{kind}/check")
async def matching_check(name: str, kind: str, request: Request):
    """The original's and the matching part's top faces as built, and how their holes line up.

    Body: {"base": original's values, "parameters": matching part's values}.
    """
    program, overrides, _ = await _target(name, request, kind)
    _, original = await _matching(name, kind, (await request.json()).get("base"))
    matching = await _profile(program, overrides)
    pieces = matching.get("solid_count", 1)
    warning = matching_part.split_warning(pieces) if kind == "spacer" and pieces > 1 else None
    return {"original": original, "matching": matching, "alignment": matching_part.hole_alignment(original, matching),
            "pieces": pieces, "warning": warning}


@app.get("/api/adapter/presets")
def adapter_presets():
    """Pattern B presets: fixed hole layouts with ISO 273 medium diameters (no model, demo-safe)."""
    return {"presets": adapter_pattern.PRESETS}


@app.post("/api/runs/{name}/matching/adapter/parse", dependencies=[Depends(_needs_keys)])
async def adapter_parse(name: str, request: Request):
    """Free text -> a validated hole pattern (Muse Spark Open, needs BASETEN_API_KEY).

    Body: {"text": "2 x M5, 60 mm apart"}. The pattern is only parsed and shown back;
    nothing is placed until the user applies it. Unreadable text is 422 with a message, never a guess.
    """
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    text = str((await request.json()).get("text") or "").strip()
    if not text or len(text) > 300:
        raise HTTPException(400, "send a short pattern description (1-300 characters)")
    if not os.getenv("BASETEN_API_KEY"):
        raise HTTPException(503, "pattern reading needs BASETEN_API_KEY in .env (Muse Spark Open)")
    try:
        return await asyncio.to_thread(adapter_pattern.interpret_pattern, text, replay.run_dir(name))
    except RuntimeError as error:  # no pattern could be read: the message goes on screen
        raise HTTPException(422, str(error))
    except Exception as error:
        raise HTTPException(502, f"Muse Spark Open did not answer: {type(error).__name__}")


@app.post("/api/runs/{name}/matching/adapter/mating/upload", dependencies=[Depends(_needs_keys)])
async def mating_upload(name: str, photo: UploadFile = File(...)):
    """Pattern B from a photo: store the mating part's photo (upright, without EXIF) as a live run.

    Measure it with the live measure stream, then turn it into a pattern below. Stored like any
    live run, so it stays out of the gallery unless opted in with public.txt.
    """
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    try:
        return live.save_upload(await photo.read())
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.post("/api/runs/{name}/matching/adapter/mating/pattern", dependencies=[Depends(_needs_keys)])
async def mating_pattern(name: str, request: Request):
    """Pattern B from a measured mating photo: its holes, centroid-relative, with measured diameters.

    Body: {"mating": live run name, "thickness": entered mating thickness in mm (default 3)}.
    No model is called here (measuring already used SAM 3.1). Unusable photos are 422 with a
    message, never a guess. The pattern, the measured outline and the entered thickness are kept
    in the mating run's 4_mating.json for the assembly check.
    """
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    body = await request.json()
    thickness = body.get("thickness", 3.0)
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)) or not 0.1 <= thickness <= 100:
        raise HTTPException(400, "send a mating thickness between 0.1 and 100 mm")
    mating = body.get("mating")
    try:
        folder = live.live_dir(mating if isinstance(mating, str) else "")
    except FileNotFoundError:
        raise HTTPException(404, f"no mating photo run named {mating!r}")
    measurements = folder / "3_measurements.json"
    if not measurements.exists():
        raise HTTPException(422, "the mating photo has not been measured yet — click the mating part first")
    table = json.loads(measurements.read_text(encoding="utf-8"))["table"]
    result, error = mating_measure.pattern_from_table(table)
    if result is None:
        raise HTTPException(422, error)
    (folder / "4_mating.json").write_text(json.dumps(
        {"pattern": result["pattern"], "summary": result["summary"], "outline_mm": result["outline_mm"],
         "outline_polygon_mm": result["outline_polygon_mm"], "thickness_mm": round(float(thickness), 2),
         "thickness_source": "entered", "main_run": name}, indent=2), encoding="utf-8")
    return {"pattern": result["pattern"], "summary": result["summary"], "mating": mating,
            "outline_mm": result["outline_mm"], "thickness_mm": round(float(thickness), 2)}


@app.post("/api/runs/{name}/matching/adapter/place")
async def adapter_placement(name: str, request: Request):
    """Place pattern B onto the original built with {"base"}: deterministic candidates, no model.

    Body: {"base": original's values, "pattern": pattern B}. 422 when no candidate keeps every
    wall: then there is no outline and no export. Works in the demo (no model involved).
    """
    body = await request.json()
    pattern, error = adapter_pattern.validate_pattern(body.get("pattern"))
    if pattern is None:
        raise HTTPException(422, f"pattern B is not usable: {error}")
    # The top-face profile does not depend on the matching kind; "cover" only lends its cache files.
    _, profile = await _matching(name, "cover", body.get("base"))
    placed = adapter_place.place_pattern(profile, pattern)
    if placed is None:
        raise HTTPException(422, "Patterns overlap — can't place pattern B")
    return {"pattern": pattern, "holes_a": profile["holes"], "box": profile["box"], "placement": placed}


@app.post("/api/runs/{name}/matching/adapter/outline")
async def adapter_outline_program(name: str, request: Request):
    """Find the adapter outline for {"base", "pattern", "outline": "auto" (default) or "fallback"}.

    "auto" asks Muse Spark Open for outlines and keeps the passing one with the fewest parameters;
    when none passes, Muse Wonder repairs (at most 2 rounds), else the deterministic fallback is used.
    Without keys (always in the demo) "auto" falls back directly. The program is cached by its
    inputs; the response names which outline was used.
    """
    body = await request.json()
    key, pattern, _, original, mode = await _adapter_key(name, body)
    mating_run = body.get("mating")  # optional: the mating photo run, when pattern B was measured
    if mating_run is not None:  # verified before the cache lookup, so bad input never hits the cache
        try:
            mating_folder = live.live_dir(mating_run if isinstance(mating_run, str) else "")
        except FileNotFoundError:
            raise HTTPException(404, f"no mating photo run named {mating_run!r}")
        if not (mating_folder / "4_mating.json").exists():
            raise HTTPException(422, "the mating photo has not been measured yet — click the mating part first")
    program, meta_path = MATCHING_DIR / f"{key}.py", MATCHING_DIR / f"{key}.json"
    if program.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {**_matching_info(name, "adapter", program),
                "parameters": matching_part.slider_parameters(program.read_text(encoding="utf-8")),
                "pattern": meta["pattern"], "placement": meta["placement"], "winner": meta["winner"],
                "outline_source": meta["outline_source"], "mating": meta.get("mating"),
                "candidates": meta["candidates"], "cached": True}
    _, profile = await _matching(name, "cover", body.get("base"))
    placed = adapter_place.place_pattern(profile, pattern)
    if placed is None:
        raise HTTPException(422, "Patterns overlap — can't place pattern B")
    holes_a = [adapter_place.profile_hole(h) for h in profile["holes"]]
    holes_b = [{"circle": (h["x"], h["y"], h["d"])} for h in placed["holes_b"]]
    margin_default = adapter_place.default_margin(profile)
    if mode == "fallback" or DEMO or not os.getenv("BASETEN_API_KEY"):
        source = adapter_outline.fallback_source(profile["holes"], placed["holes_b"], profile["thickness"],
                                                 pattern["label"], margin_default, f"{name}_adapter.py")
        outline_source, rows, winner = "fallback", [], None
    else:
        rows = await asyncio.to_thread(adapter_outline.search_adapter_outlines, holes_a, holes_b,
                                       profile["thickness"], _adapter_build, MATCHING_DIR, key,
                                       adapter_outline.ADAPTER_CANDIDATE_COUNT, replay.run_dir(name),
                                       margin_default=margin_default)
        winner = adapter_outline.pick_adapter_winner(rows)
        if winner is None and os.getenv("MODEL_API_KEY"):
            try:
                repaired = await asyncio.to_thread(
                    adapter_outline.repair_adapter_outlines, holes_a, holes_b, profile["thickness"],
                    _adapter_build, [row for row in rows if not row.get("ok")], MATCHING_DIR, key,
                    replay.run_dir(name), margin_default=margin_default)
            except Exception:
                repaired = {"passed": False, "rows": []}
            rows = rows + repaired["rows"]
            if repaired["passed"]:
                winner = repaired["result"]
        if winner is None:
            source = adapter_outline.fallback_source(profile["holes"], placed["holes_b"], profile["thickness"],
                                                     pattern["label"], margin_default, f"{name}_adapter.py")
            outline_source = "fallback"
        elif str(winner.get("label", "")).startswith("R"):
            source = Path(winner["file"]).read_text(encoding="utf-8")
            outline_source = "Muse Wonder repair"
        else:
            source = Path(winner["file"]).read_text(encoding="utf-8")
            outline_source = "Muse Spark Open"
    meta = {"pattern": pattern, "placement": placed, "holes_a": profile["holes"], "margin_default": margin_default,
            "thickness": profile["thickness"], "outline_source": outline_source,
            "mating": {"run": mating_run} if mating_run is not None else None,
            "winner": winner["candidate"] if winner else None, "candidates": rows}
    MATCHING_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in ((meta_path, json.dumps(meta)), (program, source)):
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return {**_matching_info(name, "adapter", program),
            "parameters": matching_part.slider_parameters(source),
            "pattern": pattern, "placement": placed, "winner": meta["winner"], "outline_source": outline_source,
            "mating": meta["mating"], "candidates": rows, "cached": False}


@app.post("/api/runs/{name}/matching/adapter/slotted")
async def adapter_slotted(name: str, request: Request):
    """The Slotted hole style for a searched outline: the Exact outline with every round hole of
    pattern A and pattern B as a slot along its pattern's long axis (2 x SHIFT_MM longer).

    Body: {"base", "pattern", "outline"}. The variant is derived from the Exact program built with
    its defaults, so it is cached by the same inputs. 422 names which wall or margin the slots
    break (then the caller keeps Exact); 404 when no outline was searched for these inputs yet.
    No model is called; works in the demo.
    """
    body = await request.json()
    key, pattern, _, _, _ = await _adapter_key(name, body)
    program = MATCHING_DIR / f"{key}.py"
    if not program.exists():
        raise HTTPException(404, "no adapter outline for these inputs yet (run the outline search first)")
    slotted, slotted_meta = MATCHING_DIR / f"slotted_{key}.py", MATCHING_DIR / f"slotted_{key}.json"
    if slotted.exists():
        meta = json.loads(slotted_meta.read_text(encoding="utf-8"))
        return {**_matching_info(name, "adapter", slotted),
                "parameters": matching_part.slider_parameters(slotted.read_text(encoding="utf-8")),
                "pattern": meta["pattern"], "placement": meta["placement"], "hole_style": "slotted",
                "outline_source": meta["outline_source"], "mating": meta.get("mating"),
                "hole_counts": meta.get("hole_counts"), "cached": True}
    profile, error = await asyncio.to_thread(_adapter_build, program)
    if error:
        raise HTTPException(422, f"the Exact program did not build with its defaults: {error.splitlines()[-1]}")
    exact_meta = json.loads(program.with_suffix(".json").read_text(encoding="utf-8"))
    slots_a = [t["form"] for t in _tagged_adapter_holes(profile["holes"], exact_meta["placement"]["holes_b"])
               if t["tag"] == "A"]
    specs, refusal = assembly_check.check_slotted_walls(
        profile["outline"], slots_a, exact_meta["placement"]["holes_b"])
    if specs is None:
        raise HTTPException(422, refusal)
    source = adapter_outline.slotted_source(profile["outline"], specs, profile["thickness"],
                                            pattern["label"], f"{name}_adapter.py")
    counts = {"slots": sum("slot" in spec for tag in ("a", "b") for spec in specs[tag]),
              "shaped": sum("slot" not in spec for tag in ("a", "b") for spec in specs[tag])}
    meta = {"pattern": exact_meta["pattern"], "placement": exact_meta["placement"],
            "margin_default": exact_meta["margin_default"], "thickness": profile["thickness"],
            "outline_source": f"{exact_meta['outline_source']} · slotted",
            "mating": exact_meta.get("mating"), "exact_key": key, "hole_counts": counts}
    MATCHING_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in ((slotted_meta, json.dumps(meta)), (slotted, source)):
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return {**_matching_info(name, "adapter", slotted),
            "parameters": matching_part.slider_parameters(source),
            "pattern": meta["pattern"], "placement": meta["placement"], "hole_style": "slotted",
            "outline_source": meta["outline_source"], "mating": meta["mating"],
            "hole_counts": counts, "cached": False}


def _tagged_adapter_holes(built_holes, holes_b):
    """A built adapter profile's holes tagged A or B: each placed B hole takes its nearest built
    hole (closest pairs first); the rest are pattern A. [{"tag", "center", "size", "form"}]."""
    tagged = []
    for hole in built_holes:
        if hole["type"] == "circle":
            tagged.append({"center": list(hole["center"]), "size": hole["diameter"],
                           "form": {"circle": (*hole["center"], hole["diameter"])}})
        else:
            xs = [p[0] for p in hole["points"]]
            ys = [p[1] for p in hole["points"]]
            tagged.append({"center": [round(sum(xs) / len(xs), 3), round(sum(ys) / len(ys), 3)],
                           "size": round(min(max(xs) - min(xs), max(ys) - min(ys)), 3),
                           "form": {"polygon": [tuple(p) for p in hole["points"]]}})
    pairs = sorted((math.dist(t["center"], [h["x"], h["y"]]), i, j)
                   for i, t in enumerate(tagged) for j, h in enumerate(holes_b))
    used_built, used_placed = set(), set()
    for _, i, j in pairs:
        if i not in used_built and j not in used_placed:
            used_built.add(i)
            used_placed.add(j)
            tagged[i]["tag"] = "B"
    for entry in tagged:
        entry.setdefault("tag", "A")
    return tagged


def _screw_groups(tagged):
    """Adapter holes grouped by size for the screw selects: {key: {"size", "default", "holes"}}."""
    groups = {}
    for entry in tagged:
        key = f"{entry['size']:.2f}"
        groups.setdefault(key, {"size": entry["size"],
                                "default": assembly_check.screw_for_diameter(entry["size"]), "holes": []})
        groups[key]["holes"].append(entry)
    return groups


def _resolve_mating(name, body, meta):
    """(measured_table, mating_json) for the mating run, or (None, None) for a stand-in plate."""
    run = body.get("mating") or (meta.get("mating") or {}).get("run")
    if run is None:
        return None, None
    try:
        folder = live.live_dir(run if isinstance(run, str) else "")
    except FileNotFoundError:
        raise HTTPException(404, f"no mating photo run named {run!r}")
    measurements, mating = folder / "3_measurements.json", folder / "4_mating.json"
    if not measurements.exists() or not mating.exists():
        raise HTTPException(422, "the mating photo has not been measured yet — click the mating part first")
    return (json.loads(measurements.read_text(encoding="utf-8"))["table"],
            json.loads(mating.read_text(encoding="utf-8")))


def _record_to_spec(record):
    """A baseline hole record as a worker spec hole (circle, slot or sampled polygon)."""
    u, v = record["center_from_part_center_mm"]
    if record["shape"] == "circle":
        return {"circle": (u, v, record["diameter_mm"])}
    if record["shape"] == "slot":
        return {"slot": (u, v, record["length_mm"], record["width_mm"], record["angle_deg"])}
    if record["shape"] == "rectangle":
        angle = math.radians(record["angle_deg"])
        ux, uy = math.cos(angle), math.sin(angle)
        half_l, half_w = record["length_mm"] / 2, record["width_mm"] / 2
        return {"polygon": [(round(u + su * half_l * ux - sv * half_w * uy, 3),
                             round(v + su * half_l * uy + sv * half_w * ux, 3))
                            for su, sv in ((1, 1), (-1, 1), (-1, -1), (1, -1))]}
    if record["shape"] == "ellipse":
        angle = math.radians(record["angle_deg"])
        ux, uy = math.cos(angle), math.sin(angle)
        points = []
        for i in range(32):
            arc = 2 * math.pi * i / 32
            lx, ly = math.cos(arc) * record["length_mm"] / 2, math.sin(arc) * record["width_mm"] / 2
            points.append((round(u + lx * ux - ly * uy, 3), round(v + lx * uy + ly * ux, 3)))
        return {"polygon": points}
    return {"polygon": [tuple(p) for p in record["polygon_mm"]]}


@app.post("/api/runs/{name}/matching/adapter/assembly")
async def adapter_assembly(name: str, request: Request):
    """The assembly check: stack original + adapter + mating plate, put each screw through the
    plates it joins, and report every screw's interference volume per plate (computed by CadQuery).

    Body: {"base", "pattern", "outline", "parameters", "hole_style" (exact/slotted),
    "error_case" ("as_measured"/"with_error"), "mating"? (else the outline's, else a stand-in plate),
    "screws"? ({size-group: "M3"-"M6" or null to skip})}. Screws sit fixed at the adapter's hole
    centers; A-screws join original + adapter, B-screws adapter + mating. No model is called;
    works in the demo. Cached by inputs; artifacts served under .../assembly/<check_id>/.
    """
    body = await request.json()
    error_case = body.get("error_case", "as_measured")
    if error_case not in assembly_check.ERROR_CASES:
        raise HTTPException(400, f"error_case must be one of: {', '.join(assembly_check.ERROR_CASES)}")
    program, overrides, _ = await _target(name, request, "adapter")
    style = body.get("hole_style", "exact")
    meta = json.loads(program.with_suffix(".json").read_text(encoding="utf-8"))
    adapter = await _profile(program, overrides)
    _, original = await _matching(name, "cover", body.get("base"))
    holes_b = meta["placement"]["holes_b"]
    tagged = _tagged_adapter_holes(adapter["holes"], holes_b)
    axis_a = assembly_check.pattern_long_axis([t["center"] for t in tagged if t["tag"] == "A"] or [[0, 0]])
    axis_b = assembly_check.pattern_long_axis([[h["x"], h["y"]] for h in holes_b])

    def shifted(holes, axis):
        """Final hole forms: error case moves each hole SHIFT_MM / 2 outward from its pattern's
        centroid along the axis; slotted style turns rounds into slots."""
        centers = [adapter_place.hole_center(hole) for hole in holes]
        moved = (assembly_check.error_shifted_centers(centers, axis) if error_case == "with_error"
                 else [list(c) for c in centers])
        final = []
        for hole, center in zip(holes, moved):
            if "circle" in hole and style == "slotted":
                _, _, diameter = hole["circle"]
                final.append({"slot": (*center, round(diameter + 2 * assembly_check.SHIFT_MM, 3),
                                       diameter, axis)})
            elif "circle" in hole:
                final.append({"circle": (*center, hole["circle"][2])})
            else:
                dx = center[0] - adapter_place.hole_center(hole)[0]
                dy = center[1] - adapter_place.hole_center(hole)[1]
                final.append({"polygon": [(round(x + dx, 3), round(y + dy, 3)) for x, y in hole["polygon"]]})
        return final

    measured_table, mating_json = _resolve_mating(name, body, meta)
    if measured_table is None:
        mating_records = [{"shape": "circle", "center_from_part_center_mm": [h["x"], h["y"]],
                           "diameter_mm": h["d"]} for h in holes_b]
        table, mating_thickness = assembly_check.stand_in_table(holes_b, adapter["thickness"])
        mating_label = assembly_check.STAND_IN_LABEL
    else:
        table, _ = assembly_check.mating_table(measured_table, mating_json, meta["placement"],
                                               meta["pattern"], mating_json["thickness_mm"])
        mating_records, mating_thickness = table["holes"], mating_json["thickness_mm"]
        mating_label = assembly_check.MATING_LABEL
    if style == "slotted":
        mating_records = [assembly_check.as_slot_record(h["center_from_part_center_mm"], h["diameter_mm"], axis_b)
                          if h["shape"] == "circle" else h for h in mating_records]
    if error_case == "with_error":
        moved = assembly_check.error_shifted_centers(
            [h["center_from_part_center_mm"] for h in mating_records], axis_b)
        for record, center in zip(mating_records, moved):
            dx, dy = center[0] - record["center_from_part_center_mm"][0], center[1] - record["center_from_part_center_mm"][1]
            record["center_from_part_center_mm"] = center
            if record["shape"] == "polygon":
                record["polygon_mm"] = [[round(x + dx, 3), round(y + dy, 3)] for x, y in record["polygon_mm"]]

    t_o, t_a, t_m = original["thickness"], adapter["thickness"], mating_thickness
    plates = [
        {"name": "original", "label": "original", "outline": original["outline"], "thickness": t_o,
         "z0": 0.0, "holes": shifted([adapter_place.profile_hole(h) for h in original["holes"]], axis_a)},
        {"name": "adapter", "label": f"adapter ({style})", "outline": adapter["outline"],
         "thickness": t_a, "z0": t_o, "holes": [t["form"] for t in tagged]},
        {"name": "mating", "label": mating_label, "outline": table["outline"]["polygon_mm"],
         "thickness": t_m, "z0": t_o + t_a, "holes": [_record_to_spec(h) for h in mating_records]},
    ]
    groups, screw_overrides = _screw_groups(tagged), body.get("screws") or {}
    for key, size in screw_overrides.items():
        if size is not None and size not in assembly_check.SHANK_DIAMETER_MM:
            raise HTTPException(400, f"unknown screw size for group {key}: {size!r} (M3-M6 or null)")
    screws, skipped = [], []
    for key in sorted(groups):
        size = screw_overrides.get(key, groups[key]["default"])
        if size is None:
            skipped.append({"group": key, "size": groups[key]["size"], "message":
                            f"no metric screw fits the Ø{groups[key]['size']} mm holes "
                            f"(smallest clearance is M3 = {adapter_pattern.ISO_273_MEDIUM['M3']} mm) — skipped"})
            continue
        for entry in sorted(groups[key]["holes"], key=lambda e: (e["center"][0], e["center"][1])):
            tag = entry["tag"]
            axis = axis_a if tag == "A" else axis_b
            screws.append({"pattern": tag, "group": key, "x": entry["center"][0], "y": entry["center"][1],
                           "shift": [1.0, 0.0] if axis == 0.0 else [0.0, 1.0],
                           "d": assembly_check.SHANK_DIAMETER_MM[size], "size": size,
                           "z0": -assembly_check.SCREW_PROTRUDE_MM if tag == "A" else t_o,
                           "z1": t_o + t_a if tag == "A" else t_o + t_a + t_m + assembly_check.SCREW_PROTRUDE_MM,
                           "plates": ["original", "adapter"] if tag == "A" else ["adapter", "mating"]})
    for position, screw in enumerate(sorted([s for s in screws if s["pattern"] == "A"], key=lambda s: (s["x"], s["y"])), 1):
        screw["id"] = f"A{position}"
    for position, screw in enumerate(sorted([s for s in screws if s["pattern"] == "B"], key=lambda s: (s["x"], s["y"])), 1):
        screw["id"] = f"B{position}"
    spec = {"version": 2, "plates": plates, "screws": screws}  # versioned: worker logic changes retire old checks
    check_id = hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    folder = MATCHING_DIR / f"asm_{check_id}"
    report_path = folder / "report.json"
    if not report_path.exists():
        error = await asyncio.to_thread(builder.assembly, spec, report_path)
        if error:
            raise HTTPException(422, f"the assembly did not build: {error.splitlines()[-1]}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    watched = []
    for screw in report["screws"]:
        watched.append({"id": screw["id"], "pattern": screw["pattern"], "size": screw["size"], "d": screw["d"],
                        "x": screw["x"], "y": screw["y"],
                        "overlap_mm3": round(screw["total_mm3"], 3),
                        "depth_mm": round(max(screw["penetration_mm"].values()), 3),
                        "verdict": ("blocked" if screw["total_mm3"] > assembly_check.INTERFERENCE_EPS_MM3
                                    else "pass")})
    watched.sort(key=lambda s: (s["pattern"], int(s["id"][1:])))
    blocked = [s for s in watched if s["verdict"] == "blocked"]
    message = (f"All {len(watched)} screws pass" if not blocked
               else f"{len(blocked)} of {len(watched)} screws blocked")
    base = f"/api/runs/{name}/matching/adapter/assembly/{check_id}"
    return {"check_id": check_id, "verdict": "blocked" if blocked else "pass", "message": message,
            "hole_style": style, "error_case": error_case, "screws": watched, "skipped": skipped,
            "groups": [{"key": key, "size": groups[key]["size"], "default": groups[key]["default"],
                        "holes": sorted(s["id"] for s in screws if s["group"] == key)}
                       for key in sorted(groups)],
            "plates": [{"name": p["name"], "label": p["label"], "thickness": p["thickness"], "z0": p["z0"],
                        "stl": f"{base}/plate_{p['name']}.stl"} for p in report["plates"]],
            "artifacts": {screw["id"]: {"stl": f"{base}/screw_{screw['id']}.stl",
                                        "clashes": [f"{base}/clash_{screw['id']}_{plate}.stl"
                                                    for plate, amount in screw["interference_mm3"].items()
                                                    if amount > 1e-9]}
                          for screw in report["screws"]}}


@app.get("/api/runs/{name}/matching/adapter/assembly/{check_id}/{artifact}")
async def assembly_artifact(name: str, check_id: str, artifact: str):
    """One assembly STL: plate_<name>, screw_<id> or clash_<id>_<plate> of a computed check."""
    if not re.fullmatch(r"[0-9a-f]{24}", check_id or ""):
        raise HTTPException(404, "unknown assembly check")
    if not re.fullmatch(r"(plate_[a-z]+|screw_[AB][0-9]+|clash_[AB][0-9]+_[a-z]+)\.stl", artifact or ""):
        raise HTTPException(404, "unknown assembly artifact")
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    path = MATCHING_DIR / f"asm_{check_id}" / artifact
    if not path.exists():
        raise HTTPException(404, "this check has no such artifact (re-run the assembly check)")
    return FileResponse(path, media_type="model/stl")


@app.post("/api/runs/{name}/matching/adapter/mating/plate")
async def mating_plate(name: str, request: Request):
    """The mating plate as an STL in adapter coordinates: the measured mating part (baseline built
    from its measured outline, holes and entered thickness) or the stand-in plate for presets.

    Body: {"base", "pattern", "outline", "mating"?}. No model is called; works in the demo.
    """
    body = await request.json()
    key, _, _, _, _ = await _adapter_key(name, body)
    program = MATCHING_DIR / f"{key}.py"
    if not program.exists():
        raise HTTPException(404, "no adapter outline for these inputs yet (run the outline search first)")
    meta = json.loads(program.with_suffix(".json").read_text(encoding="utf-8"))
    measured_table, mating_json = _resolve_mating(name, body, meta)
    if measured_table is None:
        _, original = await _matching(name, "cover", body.get("base"))
        adapter = await _profile(program, {})
        table, thickness = assembly_check.stand_in_table(meta["placement"]["holes_b"], adapter["thickness"])
        label = assembly_check.STAND_IN_LABEL
    else:
        adapter = await _profile(program, {})
        table, _ = assembly_check.mating_table(measured_table, mating_json, meta["placement"],
                                               meta["pattern"], mating_json["thickness_mm"])
        thickness, label = mating_json["thickness_mm"], assembly_check.MATING_LABEL
    plate_id = hashlib.sha256(json.dumps([table, thickness], sort_keys=True).encode("utf-8")).hexdigest()[:24]
    source_path, stl_path = MATCHING_DIR / f"ghost_{plate_id}.py", MATCHING_DIR / f"ghost_{plate_id}.stl"
    if not stl_path.exists():
        MATCHING_DIR.mkdir(parents=True, exist_ok=True)
        source_path.write_text(baseline_cad.baseline_code(table, thickness), encoding="utf-8")
        error = await asyncio.to_thread(builder.build, source_path, stl_path, {})
        if error:
            raise HTTPException(422, f"the mating plate did not build: {error.splitlines()[-1]}")
    return {"plate_id": plate_id, "label": label, "thickness": thickness,
            "stl": f"/api/runs/{name}/matching/adapter/mating/plate/{plate_id}.stl"}


@app.get("/api/runs/{name}/matching/adapter/mating/plate/{plate_id}.stl")
async def mating_plate_stl(name: str, plate_id: str):
    """The mating plate STL built above."""
    if not re.fullmatch(r"[0-9a-f]{24}", plate_id or ""):
        raise HTTPException(404, "unknown mating plate")
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    path = MATCHING_DIR / f"ghost_{plate_id}.stl"
    if not path.exists():
        raise HTTPException(404, "no such mating plate (build it first)")
    return FileResponse(path, media_type="model/stl")


@app.post("/api/runs/{name}/voice/transcribe", dependencies=[Depends(_needs_keys)])
async def voice_transcribe(name: str, audio: UploadFile = File(...)):
    """A spoken command (mono 16-bit WAV, 16 or 24 kHz, at most 30 s) as text, by Muse Voice Transcribe."""
    if not os.getenv("MODEL_API_KEY"):
        raise HTTPException(503, "speech needs MODEL_API_KEY in .env (Muse Voice Transcribe)")
    data = await audio.read()
    if len(data) > 4 * 1024 * 1024:
        raise HTTPException(413, "a command recording is at most 4 MB")
    try:
        keywords = [p["name"].replace("_", " ") for p in replay.winner(name)["parameters"]]
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    try:
        return await asyncio.to_thread(voice_edit.transcribe, data, keywords, replay.run_dir(name))
    except ValueError as error:  # not a WAV the endpoint accepts, or too long
        raise HTTPException(400, str(error))
    except Exception as error:
        raise HTTPException(502, f"Muse Voice Transcribe did not answer: {str(error)[:200]}")


@app.post("/api/runs/{name}/voice/interpret", dependencies=[Depends(_needs_keys)])
async def voice_interpret(name: str, request: Request):
    """Voice editing: {"command": text, "parameters": {name: current value}} -> the proposed changes (not applied).

    Muse Spark Open turns the command into changes of the program's named parameters (needs BASETEN_API_KEY).
    """
    body = await request.json()
    command = str(body.get("command") or "").strip()
    if not command or len(command) > 300:
        raise HTTPException(400, "send a short command (1-300 characters)")
    overrides = await _parameters(name, request)  # only the program's own numeric parameters
    current = {p["name"]: overrides.get(p["name"], p["default"]) for p in replay.winner(name)["parameters"]}
    if not os.getenv("BASETEN_API_KEY"):
        raise HTTPException(503, "voice editing needs BASETEN_API_KEY in .env (Muse Spark Open)")
    try:
        return await asyncio.to_thread(voice_edit.interpret, command, current, replay.run_dir(name))
    except Exception as error:  # the model call failed: say so, do not crash
        raise HTTPException(502, f"Muse Spark Open did not answer: {type(error).__name__}")


@app.get("/api/runs/{name}/irregularities")
def run_irregularities(name: str):
    """The break cues summed up for the "no design found" panel (rough edges, missing material, holes)."""
    try:
        return replay.irregularities(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


@app.get("/api/runs/{name}/repair/stream", dependencies=[Depends(_needs_keys)])
async def repair_again(name: str):
    """Run the Muse Wonder repair again on a saved run where no candidate passed (needs MODEL_API_KEY)."""
    try:
        replay.run_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    if not os.getenv("MODEL_API_KEY"):
        raise HTTPException(503, "repair needs MODEL_API_KEY in .env (Muse Wonder)")
    return job_stream(lambda emit: live.repair_again_job(name, builder, emit))


@app.get("/api/runs/{name}/completion")
def run_completion(name: str):
    """Screen 4: the completion suggestion (Muse Wonder) for a part that looks broken, or {"available": false}."""
    try:
        data = replay.completion(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    return {"available": False} if data is None else {"available": True, **data}


@app.get("/api/runs/{name}/completion/added.stl")
def completion_added(name: str):
    """The material the suggestion adds, for showing it in its own tone in the 3D view."""
    try:
        path = replay.run_dir(name) / "6_completion" / "added.stl"
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    if not path.exists():
        raise HTTPException(404, "the suggestion adds no material")
    return Response(path.read_bytes(), media_type="model/stl")


@app.post("/api/runs/{name}/completion/{decision}")
async def completion_decision(name: str, decision: str, request: Request):
    """Apply or ignore the suggestion ("undo" clears the answer); applying makes the completed program the result.

    Body (optional): {"values": {parameter: number}}, the answers to the estimated and optional parts.
    """
    if decision not in ("apply", "ignore", "undo"):
        raise HTTPException(400, "decision must be apply, ignore or undo")
    body = await request.body()
    values = (json.loads(body) or {}).get("values") if body else None
    try:
        replay.decide_completion(name, None if decision == "undo" else decision, values)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    except ValueError as error:
        raise HTTPException(422, str(error))
    return replay.completion(name)


@app.get("/api/runs/{name}/capture-fit.png")
def capture_fit(name: str):
    """Screen 4 inset: the top-down photo with the result's silhouette outline, aligned as the IoU is."""
    try:
        return Response(replay.capture_fit_png(name), media_type="image/png")
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))


DOWNLOADS = {  # format -> (file suffix, media type)
    "stl": (".stl", "model/stl"),
    "step": (".step", "application/step"),
    "py": (".py", "text/x-python"),
    "dxf": (".dxf", "image/vnd.dxf"),
    "pdf": ("_template_1to1.pdf", "application/pdf"),
    "zip": (".zip", "application/zip"),
}


async def _profile(program, overrides):
    """The built part's top face (outline, holes, thickness) for drawings, DXF and the 1:1 template."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{uuid.uuid4().hex}.profile.json").resolve()
    error = await asyncio.to_thread(builder.build, program, output, overrides)
    if error:
        raise HTTPException(422, f"the program did not build with these values: {error.splitlines()[-1]}")
    data = json.loads(output.read_text(encoding="utf-8"))
    output.unlink()
    return data


@app.post("/api/runs/{name}/drawing")
async def drawing(name: str, request: Request, match: str | None = None):
    """Screen 5: the part's top-face profile and thickness for the technical drawing (mm)."""
    program, overrides, _ = await _target(name, request, match)
    about = replay.winner(name) if match is None else _matching_info(name, match, program)
    profile = await _profile(program, overrides)
    if match == "spacer" and profile.get("solid_count", 1) > 1:
        raise HTTPException(422, matching_part.split_warning(profile["solid_count"]))
    return {"name": about["name"], "program": about["program"], "source": about["source"],
            "profile": profile}


@app.post("/api/runs/{name}/download")
async def download(name: str, request: Request, format: str = "stl", match: str | None = None):
    """Screen 5: the part with the current slider values as STL, STEP, DXF, the CadQuery program (.py),
    the 1:1 print template (PDF) or all of them (.zip)."""
    if format not in DOWNLOADS:
        raise HTTPException(400, f"format must be one of {', '.join(DOWNLOADS)}")
    program, overrides, label = await _target(name, request, match)
    suffix, media_type = DOWNLOADS[format]
    profile = None
    if match == "spacer":  # a split gasket's outline, DXF and PDF would show only one piece: refuse, don't mislead
        profile = await _profile(program, overrides)
        pieces = profile.get("solid_count", 1)
        if pieces > 1:
            raise HTTPException(422, matching_part.split_warning(pieces))
    try:
        data = await _download_data(program, overrides, format, label, profile)
    except ValueError as error:  # e.g. the part does not fit on an A3 page
        raise HTTPException(422, str(error))
    filename = f"reversecad_{label}{suffix}"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _download_data(program, overrides, format, label, profile=None):
    if format == "py":  # the parametric program itself, with the slider values as its new defaults
        return replay.replace_defaults(program.read_text(encoding="utf-8"), overrides).encode("utf-8")
    if format == "dxf":
        return drawing_export.dxf_bytes(profile or await _profile(program, overrides), label)
    if format == "pdf":
        return drawing_export.template_pdf(profile or await _profile(program, overrides), label)
    if format == "zip":  # every format at once
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in ("step", "stl", "dxf", "py", "pdf"):
                try:
                    archive.writestr(f"reversecad_{label}{DOWNLOADS[part][0]}",
                                     await _download_data(program, overrides, part, label, profile))
                except ValueError:  # too large for the template: the other files still go in
                    continue
        return stream.getvalue()
    return await _export(program, overrides, DOWNLOADS[format][0])


# ---------- live mode ----------
def _event_text(event):
    return f"event: {event['type']}\ndata: {json.dumps(event, default=lambda o: o.item())}\n\n"


def job_stream(job):
    """Run job(emit) in a thread and stream what it emits as server-sent events.

    An exception becomes an 'error' event, so the page can show it instead of waiting forever.
    """
    loop = asyncio.get_running_loop()
    events = asyncio.Queue()

    def emit(event):
        loop.call_soon_threadsafe(events.put_nowait, event)

    def run():
        try:
            job(emit)
        except Exception as error:
            emit({"type": "error", "message": f"{type(error).__name__}: {error}"})
        finally:
            emit(None)

    threading.Thread(target=run, daemon=True).start()

    async def stream():
        while (event := await events.get()) is not None:
            yield _event_text(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/live/upload", dependencies=[Depends(_needs_keys)])
async def live_upload(photo: UploadFile = File(...)):
    """Screen 1 live: store the photo (upright, without EXIF) as a new live run."""
    try:
        return live.save_upload(await photo.read())
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.get("/api/live/{name}/measure/stream", dependencies=[Depends(_needs_keys)])
async def live_measure(name: str, x: int, y: int):
    """Screens 1-2 live: SAM and measurement for the click at (x, y), with progress events."""
    try:
        live.live_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    return job_stream(lambda emit: live.measure_job(name, (x, y), emit))


@app.get("/api/live/{name}/candidates/stream", dependencies=[Depends(_needs_keys)])
async def live_candidates(name: str, count: int = 5, thickness: float = 3.0):
    """Screen 3 live: candidates from Muse Spark Open, each checked and sent as soon as it arrives."""
    try:
        replay.run_dir(name)  # must be measured first
        live.live_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    if not 1 <= count <= 10 or not 0.1 <= thickness <= 100:
        raise HTTPException(400, "count must be 1-10 and thickness 0.1-100 mm")
    return job_stream(lambda emit: live.candidates_job(name, count, thickness, builder.silhouette, emit, builder))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/favicon.ico")
def favicon():
    """For anything asking the default address instead of reading the page's icon link."""
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
