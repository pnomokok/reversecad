"""Record every model call a run makes (tokens, images, seconds) and estimate its cost in dollars.

Each call appends one JSON line to <run folder>/usage.jsonl; cached answers are not calls and are
not recorded. summarize() adds the lines up per model. Prices and where they come from are in
PRICES; a model without a known price is counted in tokens only (its cost shows as unknown).
"""
import json
import threading
import time
from pathlib import Path

SAM = "sam-3.1"
SPARK_OPEN = "meta-models/muse-spark-open-1026"
WONDER = "muse-wonder-1.0"
VOICE = "muse-voice-transcribe-1.0"

PRICES = {  # USD
    SAM: {"per_image": 0.0025, "source": "Meta Model API docs (CLAUDE.md)"},
    WONDER: {"input_per_million": 4.0, "output_per_million": 20.0, "source": "project document"},
    VOICE: {"per_audio_hour": 0.18, "source": "Meta docs, Speech to text (whole seconds billed)"},
    SPARK_OPEN: {"input_per_million": 1.25, "output_per_million": 4.25, "unverified": True,
                 "source": "third-party listing; to be checked in the Baseten dashboard"},
}
FILE_NAME = "usage.jsonl"
_lock = threading.Lock()  # candidate requests finish on several threads


def record(folder, model, purpose, input_tokens=0, output_tokens=0, reasoning_tokens=0, images=0, seconds=None,
           audio_seconds=0):
    """Append one call to the run's ledger."""
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "model": model, "purpose": purpose,
             "input_tokens": int(input_tokens or 0), "output_tokens": int(output_tokens or 0),
             "reasoning_tokens": int(reasoning_tokens or 0), "images": int(images or 0),
             "audio_seconds": int(audio_seconds or 0),
             "seconds": round(float(seconds), 1) if seconds is not None else None}
    with _lock, open(Path(folder) / FILE_NAME, "a", encoding="utf-8") as file:
        file.write(json.dumps(entry) + "\n")


def record_response(folder, model, purpose, response, seconds=None):
    """Record a Chat Completions response (a dict, as saved): its usage block; failed requests count as 0 tokens."""
    usage = (response or {}).get("usage") or {}
    details = usage.get("completion_tokens_details") or {}
    record(folder, model, purpose, usage.get("prompt_tokens"), usage.get("completion_tokens"),
           details.get("reasoning_tokens"), seconds=seconds if seconds is not None else (response or {}).get("elapsed_s"))


def cost(model, input_tokens, output_tokens, images, audio_seconds=0):
    """Estimated dollars, or None when the model's price is not known."""
    price = PRICES.get(model)
    if price is None:
        return None
    return (images * price.get("per_image", 0) + audio_seconds * price.get("per_audio_hour", 0) / 3600
            + input_tokens * price.get("input_per_million", 0) / 1e6
            + output_tokens * price.get("output_per_million", 0) / 1e6)


def summarize(folder):
    """Per model: calls, tokens, images, seconds and estimated cost; plus the total of the known costs."""
    path = Path(folder) / FILE_NAME
    models = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            total = models.setdefault(entry["model"], {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                      "reasoning_tokens": 0, "images": 0, "audio_seconds": 0,
                                                      "seconds": 0.0})
            total["calls"] += 1
            for key in ("input_tokens", "output_tokens", "reasoning_tokens", "images", "audio_seconds"):
                total[key] += entry.get(key, 0)  # older lines have no audio_seconds
            total["seconds"] = round(total["seconds"] + (entry["seconds"] or 0), 1)
    for model, total in models.items():
        dollars = cost(model, total["input_tokens"], total["output_tokens"], total["images"], total["audio_seconds"])
        total["cost_usd"] = round(dollars, 4) if dollars is not None else None
        total["price_unverified"] = bool((PRICES.get(model) or {}).get("unverified"))
    known = [t["cost_usd"] for t in models.values() if t["cost_usd"] is not None]
    return {"models": models, "known_cost_usd": round(sum(known), 4),
            "unpriced_models": [m for m, t in models.items() if t["cost_usd"] is None],
            "unverified_price_models": [m for m, t in models.items() if t["price_unverified"]]}


def describe(summary):
    """Short printable lines for a run summary."""
    lines = []
    for model, t in summary["models"].items():
        price = f"${t['cost_usd']:.4f}" if t["cost_usd"] is not None else "price unknown"
        price += " (unverified price)" if t.get("price_unverified") else ""
        amount = (f"{t['images']} images" if t["images"] else f"{t['audio_seconds']} s of audio" if t["audio_seconds"]
                  else f"{t['input_tokens']} in / {t['output_tokens']} out tokens")
        lines.append(f"{model}: {t['calls']} calls, {amount}, {t['seconds']} s, {price}")
    lines.append(f"known cost ${summary['known_cost_usd']:.4f}"
                 + (f" (+ unpriced: {', '.join(summary['unpriced_models'])})" if summary["unpriced_models"] else ""))
    return lines
