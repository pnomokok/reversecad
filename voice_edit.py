"""Voice editing: a short spoken (or typed) command becomes named parameter changes, shown before they apply.

Muse Spark Open reads the command and the program's parameters with their current values and answers
with the changes as JSON ("make the holes 2 mm bigger" -> hole_diameter 6.0 -> 8.0). The answer is
checked here: only the program's own parameters, numbers, nothing negative. The app shows the changes
and applies them only on Apply. (Speech to text, Muse Voice Transcribe, is not wired in yet: its
request format is to be confirmed from Meta's docs.)
"""
import json
import re
import time

import usage_ledger
from baseten_client import MODEL, make_client

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
