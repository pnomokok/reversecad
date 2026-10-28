"""Voice editing: a short spoken (or typed) command becomes named parameter changes, shown before they apply.

Muse Spark Open reads the command and the program's parameters with their current values and answers
with the changes as JSON ("make the holes 2 mm bigger" -> hole_diameter 6.0 -> 8.0). The answer is
checked here: only the program's own parameters, numbers, nothing negative. The app shows the changes
and applies them only on Apply.

Speech to text is Muse Voice Transcribe's file endpoint (Meta docs, "Speech to text"): POST
/v1/asr/transcribe, multipart with a "request" JSON part and an "audio" part that must be a mono,
16-bit PCM WAV at 16 or 24 kHz (the browser converts its recording before uploading). PUSH_TO_TALK:
the user marks the turn with the mic button. $0.18 per hour of audio, billed in whole seconds.
"""
import io
import json
import os
import re
import time
import wave

import requests
from dotenv import load_dotenv

import usage_ledger
from baseten_client import MODEL, make_client

TRANSCRIBE_URL = "https://api.meta.ai/v1/asr/transcribe"
MAX_COMMAND_SECONDS = 30
LANGUAGES = ["English", "Turkish"]  # a hint, not a limit: commands may come in either

REASONING_EFFORT = "low"  # a one-line command; low keeps the answer to a few seconds
MAX_TOKENS = 4000

PROMPT = """You turn a short edit command for a CAD part into changes of the part program's named parameters.

The program's parameters, with their current values (lengths in mm):
{parameters}

Command: "{command}"

Rules:
- Change only parameters from the list, by their exact names.
- Work out the new value from the current one: "2 mm bigger" adds 2, "half as thick" halves, "make it 100 long" sets 100.
- "The holes" means every hole parameter; "longer" or "wider" means the overall length or width.
- If the command is unclear, or asks for something no parameter controls, make no change and say so in the note.

Reply with JSON only, no other text:
{{"changes": [{{"name": "<parameter>", "value": <new number>}}], "note": "<one short sentence: what you did, or why nothing>"}}"""


def interpret(command, parameters, ledger_folder=None, client=None):
    """{"changes": [{"name", "from", "to"}], "note", "seconds"} for a command; parameters: name -> current value."""
    listing = "\n".join(f"- {name} = {value}" for name, value in parameters.items())
    started = time.perf_counter()
    response = (client or make_client()).chat.completions.create(
        model=MODEL, max_tokens=MAX_TOKENS, reasoning_effort=REASONING_EFFORT,
        messages=[{"role": "user", "content": PROMPT.format(parameters=listing, command=command.strip())}])
    seconds = round(time.perf_counter() - started, 1)
    if ledger_folder is not None:
        usage_ledger.record_response(ledger_folder, usage_ledger.SPARK_OPEN, "voice edit", response.model_dump(), seconds)
    answer = parse_answer(response.choices[0].message.content, parameters)
    return {**answer, "command": command, "seconds": seconds}


def parse_answer(text, parameters):
    """The checked changes: known parameters only, numbers, not negative, and actually different."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    changes, ignored = [], []
    for change in data.get("changes") or []:
        name, value = change.get("name"), change.get("value")
        if name not in parameters or not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            ignored.append(str(name))
            continue
        if abs(float(value) - float(parameters[name])) > 1e-9:
            changes.append({"name": name, "from": float(parameters[name]), "to": round(float(value), 4)})
    note = str(data.get("note") or ("I could not read the answer." if not match else ""))
    if ignored:
        note += f" (Left out: {', '.join(ignored)}, not parameters of this program.)"
    return {"changes": changes, "note": note.strip()}


def check_wav(data):
    """Seconds of audio in a WAV the transcribe endpoint accepts (mono, 16-bit PCM, 16 or 24 kHz); ValueError otherwise."""
    try:
        with wave.open(io.BytesIO(data)) as audio:
            channels, width, rate, frames = audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()
    except (wave.Error, EOFError) as error:
        raise ValueError(f"not a WAV file: {error}") from error
    if channels != 1 or width != 2 or rate not in (16000, 24000):
        raise ValueError(f"needs mono 16-bit PCM at 16 or 24 kHz (got {channels} channel(s), {8 * width} bit, {rate} Hz)")
    seconds = frames / rate
    if seconds > MAX_COMMAND_SECONDS:
        raise ValueError(f"a command is at most {MAX_COMMAND_SECONDS} s ({seconds:.0f} s sent)")
    return seconds


def transcribe(wav_bytes, keywords=(), ledger_folder=None):
    """{"transcript", "seconds", "audio_seconds"} for a short spoken command (Muse Voice Transcribe)."""
    audio_seconds = check_wav(wav_bytes)
    load_dotenv()
    api_key = os.getenv("MODEL_API_KEY")
    if not api_key:
        raise RuntimeError("MODEL_API_KEY is missing from .env")
    settings = {"mode": "PUSH_TO_TALK", "model": usage_ledger.VOICE, "audioEncoding": "WAV",
                "languageBias": LANGUAGES, "keywords": list(keywords)[:50]}
    started = time.perf_counter()
    response = requests.post(TRANSCRIBE_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=60,
                             files={"request": (None, json.dumps(settings), "application/json"),
                                    "audio": ("command.wav", wav_bytes, "audio/wav")})
    seconds = round(time.perf_counter() - started, 1)
    if response.status_code != 200:
        raise RuntimeError(f"Muse Voice Transcribe answered {response.status_code}: {response.text[:200]}")
    data = response.json()
    billed = (data.get("audioDurationMs") or audio_seconds * 1000) // 1000  # billed in whole seconds
    if ledger_folder is not None:
        usage_ledger.record(ledger_folder, usage_ledger.VOICE, "voice command", audio_seconds=billed, seconds=seconds)
    return {"transcript": (data.get("transcript") or "").strip(), "seconds": seconds, "audio_seconds": billed}
