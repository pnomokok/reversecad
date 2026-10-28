"""FastAPI back end for the ReverseCAD web app.

Serves the front end (webapp/static/) and a JSON API. Saved runs (outputs/e2e/<scene>/)
replay without calling any model; live mode (/api/live/...) runs the pipeline on an
uploaded photo and saves it as a run in the same format.

Run from the repository root:
    .venv\\Scripts\\python.exe -m uvicorn webapp.server:app --reload
then open http://127.0.0.1:8000
"""
import asyncio
import json
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from webapp import live, replay
from webapp.builder import Builder

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
def completion_decision(name: str, decision: str):
    """Apply or ignore the suggestion ("undo" clears the answer); applying makes the completed program the result."""
    if decision not in ("apply", "ignore", "undo"):
        raise HTTPException(400, "decision must be apply, ignore or undo")
    try:
        replay.decide_completion(name, None if decision == "undo" else decision)
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
}


@app.post("/api/runs/{name}/download")
async def download(name: str, request: Request, format: str = "stl"):
    """Screen 5: the part with the current slider values as STL, STEP or the CadQuery program (.py)."""
    if format not in DOWNLOADS:
        raise HTTPException(400, f"format must be one of {', '.join(DOWNLOADS)}")
    overrides = await _parameters(name, request)
    suffix, media_type = DOWNLOADS[format]
    if format == "py":  # the parametric program itself, with the slider values as its new defaults
        data = replay.program_with_defaults(name, overrides).encode("utf-8")
    else:
        data = await _export(name, overrides, suffix)
    filename = f"reversecad_{name}{suffix}"
    return Response(data, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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


@app.post("/api/live/upload")
async def live_upload(photo: UploadFile = File(...)):
    """Screen 1 live: store the photo (upright, without EXIF) as a new live run."""
    try:
        return live.save_upload(await photo.read())
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.get("/api/live/{name}/measure/stream")
async def live_measure(name: str, x: int, y: int):
    """Screens 1-2 live: SAM and measurement for the click at (x, y), with progress events."""
    try:
        live.live_dir(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))
    return job_stream(lambda emit: live.measure_job(name, (x, y), emit))


@app.get("/api/live/{name}/candidates/stream")
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
