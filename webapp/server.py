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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from webapp import replay

STATIC = Path(__file__).parent / "static"
REPLAY_DELAY_S = 0.4  # pause between replayed candidate events
app = FastAPI(title="ReverseCAD")


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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
