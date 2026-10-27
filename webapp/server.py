"""FastAPI back end for the ReverseCAD web app.

Serves the front end (webapp/static/) and a JSON API. For now it replays saved
runs (outputs/e2e/<scene>/) without calling any model; the live pipeline is
connected in a later step.

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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from webapp import replay
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
async def candidate_stream(name: str):
    """Screen 3: candidates as server-sent events, one by one as they would arrive live, then 'done'."""
    try:
        events = replay.candidate_events(name)
    except FileNotFoundError as error:
        raise HTTPException(404, str(error))

    async def stream():
        for event in events:
            await asyncio.sleep(REPLAY_DELAY_S)  # replay pace; live mode sends as candidates finish
            yield f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/runs/{name}/candidates/{candidate}/silhouette.png")
def candidate_silhouette(name: str, candidate: int):
    try:
        return Response(replay.silhouette_png(name, candidate), media_type="image/png")
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


async def _export(name, overrides, suffix):
    """Build the result program with overrides into a .stl or .step file; return its bytes."""
    program, _ = replay.result_program(name)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    output = (MODEL_DIR / f"{name}_{uuid.uuid4().hex}{suffix}").resolve()
    error = await asyncio.to_thread(builder.build, program, output, overrides)
    if error:
        raise HTTPException(422, f"the program did not build with these values: {error.splitlines()[-1]}")
    data = output.read_bytes()
    output.unlink()
    return data


@app.post("/api/runs/{name}/model")
async def build_model(name: str, request: Request):
    """Screen 4: build with the posted parameter values; binary STL for the viewer.

    Body: {"parameters": {"name": value, ...}}; only the program's own numeric parameters are accepted.
    """
    return Response(await _export(name, await _parameters(name, request), ".stl"), media_type="model/stl")


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
