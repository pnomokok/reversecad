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
import os
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
import drawing_export
import matching_part
import voice_edit
from webapp import live, replay
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
    made_from = json.dumps([kind, original.read_text(encoding="utf-8"), overrides], sort_keys=True)
    key = hashlib.sha256(made_from.encode("utf-8")).hexdigest()[:24]
    program, profile_path = MATCHING_DIR / f"{key}.py", MATCHING_DIR / f"{key}.json"
    if not program.exists():
        profile = await _profile(original, overrides)
        MATCHING_DIR.mkdir(parents=True, exist_ok=True)
        # Each file appears whole: another request for the same part may be reading it.
        for path, text in ((profile_path, json.dumps(profile)),
                           (program, matching_part.matching_source(profile, kind, original.name))):
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
    made_from = json.dumps(["adapter", original.read_text(encoding="utf-8"), overrides, pattern, mode], sort_keys=True)
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
        program = MATCHING_DIR / f"{key}.py"
        if not program.exists():
            raise HTTPException(404, "no adapter outline for these inputs yet (run the outline search first)")
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
    _, original = await _matching(name, "cover", (await request.json()).get("base"))
    matching = await _profile(program, overrides)
    margins = [adapter_place.hole_to_outline(adapter_place.profile_hole(h), matching["outline"])
               for h in matching["holes"]]
    return {"original": original, "matching": matching,
            "alignment": matching_part.hole_alignment(original, matching),
            "holes_b": meta["placement"]["holes_b"], "label_b": meta["pattern"]["label"],
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
    program, meta_path = MATCHING_DIR / f"{key}.py", MATCHING_DIR / f"{key}.json"
    if program.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {**_matching_info(name, "adapter", program),
                "parameters": matching_part.slider_parameters(program.read_text(encoding="utf-8")),
                "pattern": meta["pattern"], "placement": meta["placement"], "winner": meta["winner"],
                "outline_source": meta["outline_source"],
                "candidates": meta["candidates"], "cached": True}
    _, profile = await _matching(name, "cover", body.get("base"))
    placed = adapter_place.place_pattern(profile, pattern)
    if placed is None:
        raise HTTPException(422, "Patterns overlap — can't place pattern B")
    holes_a = [adapter_place.profile_hole(h) for h in profile["holes"]]
    holes_b = [{"circle": (h["x"], h["y"], h["d"])} for h in placed["holes_b"]]
    if mode == "fallback" or DEMO or not os.getenv("BASETEN_API_KEY"):
        source = adapter_outline.fallback_source(profile["holes"], placed["holes_b"], profile["thickness"],
                                                 pattern["label"], original.name)
        outline_source, rows, winner = "fallback", [], None
    else:
        rows = await asyncio.to_thread(adapter_outline.search_adapter_outlines, holes_a, holes_b,
                                       profile["thickness"], _adapter_build, MATCHING_DIR, key,
                                       adapter_outline.ADAPTER_CANDIDATE_COUNT, replay.run_dir(name))
        winner = adapter_outline.pick_adapter_winner(rows)
        if winner is None and os.getenv("MODEL_API_KEY"):
            try:
                repaired = await asyncio.to_thread(
                    adapter_outline.repair_adapter_outlines, holes_a, holes_b, profile["thickness"],
                    _adapter_build, [row for row in rows if not row.get("ok")], MATCHING_DIR, key,
                    replay.run_dir(name))
            except Exception:
                repaired = {"passed": False, "rows": []}
            rows = rows + repaired["rows"]
            if repaired["passed"]:
                winner = repaired["result"]
        if winner is None:
            source = adapter_outline.fallback_source(profile["holes"], placed["holes_b"], profile["thickness"],
                                                     pattern["label"], original.name)
            outline_source = "fallback"
        elif str(winner.get("label", "")).startswith("R"):
            source = Path(winner["file"]).read_text(encoding="utf-8")
            outline_source = "Muse Wonder repair"
        else:
            source = Path(winner["file"]).read_text(encoding="utf-8")
            outline_source = "Muse Spark Open"
    meta = {"pattern": pattern, "placement": placed, "holes_a": profile["holes"],
            "thickness": profile["thickness"], "outline_source": outline_source,
            "winner": winner["candidate"] if winner else None, "candidates": rows}
    MATCHING_DIR.mkdir(parents=True, exist_ok=True)
    for path, text in ((meta_path, json.dumps(meta)), (program, source)):
        temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    return {**_matching_info(name, "adapter", program),
            "parameters": matching_part.slider_parameters(source),
            "pattern": pattern, "placement": placed, "winner": meta["winner"], "outline_source": outline_source,
            "candidates": rows, "cached": False}


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
