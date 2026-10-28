"""FastAPI back end for the ReverseCAD web app.

Serves the front end (webapp/static/) and a JSON API. Saved runs (outputs/e2e/<scene>/)
replay without calling any model; live mode (/api/live/...) runs the pipeline on an
uploaded photo and saves it as a run in the same format.

Run from the repository root:
    .venv\\Scripts\\python.exe -m uvicorn webapp.server:app --reload
then open http://127.0.0.1:8000
"""
import asyncio
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

import drawing_export
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
            "voice": not DEMO and bool(os.getenv("BASETEN_API_KEY"))}


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


async def _parameters(name, request):
    """The posted {"parameters": {...}}, checked: only the program's own numeric parameters."""
    try:
        allowed = {p["name"] for p in replay.winner(name)["parameters"]}
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    overrides = {}
    for key, value in ((await request.json()).get("parameters") or {}).items():
        if key not in allowed or not isinstance(value, (int, float)) or isinstance(value, bool):
            raise HTTPException(400, f"unknown or non-numeric parameter: {key}")
        overrides[key] = float(value)
    return overrides


async def _export(name, overrides, suffix, with_features=False):
    """Build the result program with overrides into a .stl or .step file; return its bytes
    (and, with_features, the model's bounding box and top-face holes)."""
    program, _ = replay.result_program(name)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{name}_{uuid.uuid4().hex}{suffix}").resolve()
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
async def build_model(name: str, request: Request):
    """Screen 4: build with the posted parameter values; binary STL for the viewer.

    Body: {"parameters": {"name": value, ...}}; only the program's own numeric parameters are accepted.
    The X-Model-Features header carries the model's bounding box and top-face holes (JSON, mm).
    """
    data, features = await _export(name, await _parameters(name, request), ".stl", with_features=True)
    return Response(data, media_type="model/stl", headers={"X-Model-Features": features})


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


async def _profile(name, overrides):
    """The built part's top face (outline, holes, thickness) for drawings, DXF and the 1:1 template."""
    program, _ = replay.result_program(name)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{name}_{uuid.uuid4().hex}.profile.json").resolve()
    error = await asyncio.to_thread(builder.build, program, output, overrides)
    if error:
        raise HTTPException(422, f"the program did not build with these values: {error.splitlines()[-1]}")
    data = json.loads(output.read_text(encoding="utf-8"))
    output.unlink()
    return data


@app.post("/api/runs/{name}/drawing")
async def drawing(name: str, request: Request):
    """Screen 5: the part's top-face profile and thickness for the technical drawing (mm)."""
    overrides = await _parameters(name, request)
    winner = replay.winner(name)
    return {"name": name, "program": winner["program"], "source": winner["source"],
            "profile": await _profile(name, overrides)}


@app.post("/api/runs/{name}/download")
async def download(name: str, request: Request, format: str = "stl"):
    """Screen 5: the part with the current slider values as STL, STEP, DXF, the CadQuery program (.py),
    the 1:1 print template (PDF) or all of them (.zip)."""
    if format not in DOWNLOADS:
        raise HTTPException(400, f"format must be one of {', '.join(DOWNLOADS)}")
    overrides = await _parameters(name, request)
    suffix, media_type = DOWNLOADS[format]
    try:
        data = await _download_data(name, overrides, format)
    except ValueError as error:  # e.g. the part does not fit on an A3 page
        raise HTTPException(422, str(error))
    filename = f"reversecad_{name}{suffix}"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


async def _download_data(name, overrides, format):
    if format == "py":  # the parametric program itself, with the slider values as its new defaults
        return replay.program_with_defaults(name, overrides).encode("utf-8")
    if format == "dxf":
        return drawing_export.dxf_bytes(await _profile(name, overrides), name)
    if format == "pdf":
        return drawing_export.template_pdf(await _profile(name, overrides), name)
    if format == "zip":  # every format at once
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            for part in ("step", "stl", "dxf", "py", "pdf"):
                try:
                    archive.writestr(f"reversecad_{name}{DOWNLOADS[part][0]}", await _download_data(name, overrides, part))
                except ValueError:  # too large for the template: the other files still go in
                    continue
        return stream.getvalue()
    return await _export(name, overrides, DOWNLOADS[format][0])


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


app.mount("/static", StaticFiles(directory=STATIC), name="static")
