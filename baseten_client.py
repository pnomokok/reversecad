"""Client for Muse Spark Open on Baseten (OpenAI-compatible Chat Completions API).

The hackathon key only works with the "-1026" model name; don't use the name
from the Baseten docs. The API key is read from BASETEN_API_KEY in .env.
"""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BASE_URL = "https://inference.baseten.co/v1"
MODEL = "meta-models/muse-spark-open-1026"


def make_client():
    load_dotenv()
    api_key = os.getenv("BASETEN_API_KEY")
    if not api_key:
        raise RuntimeError("BASETEN_API_KEY is missing from .env")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def image_data_url(path):
    """Encode a local PNG/JPEG file as a base64 data URL."""
    path = Path(path)
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"
