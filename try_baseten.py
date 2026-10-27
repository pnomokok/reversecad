"""First calls to Muse Spark Open: one text prompt, one image prompt.

Prints the whole response object (long strings shortened) so we can see which
fields carry the reasoning and which carry the answer, plus token usage.
Full responses are saved under outputs/baseten/. Generated code is saved, not run.

Run: .venv\\Scripts\\python.exe try_baseten.py
"""
import json
import re
from pathlib import Path

from baseten_client import MODEL, image_data_url, make_client

OUTPUT_DIR = Path("outputs") / "baseten"
MAX_TOKENS = 8000  # reasoning tokens count toward this limit

TEXT_PROMPT = (
    "Write a CadQuery function that makes an 80x40x3 mm plate with four 6 mm holes, "
    "8 mm from each edge."
)
IMAGE_PROMPT = "Describe this shape: outline and holes"
IMAGE_PATH = Path("outputs") / "holed_plate_top.png"


def shorten(value, limit=300):
    """Recursively shorten long strings so the structure stays readable."""
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [{len(value)} chars total]"
    if isinstance(value, dict):
        return {key: shorten(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [shorten(item, limit) for item in value]
    return value


def report(name, response):
    data = response.model_dump()
    (OUTPUT_DIR / f"{name}_response.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\n===== {name}: full response (long strings shortened) =====")
    print(json.dumps(shorten(data), indent=2))
    print(f"----- {name}: token usage -----")
    print(json.dumps(data.get("usage"), indent=2))


def extract_python_block(text):
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text or "", re.DOTALL)
    return match.group(1) if match else None


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    client = make_client()

    # 1. Text prompt -> CadQuery code (saved, not executed)
    text_response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": TEXT_PROMPT}],
    )
    report("text", text_response)
    content = text_response.choices[0].message.content
    code = extract_python_block(content)
    if code:
        code_path = OUTPUT_DIR / "plate_from_text.py"
        code_path.write_text(code, encoding="utf-8")
        print(f"saved generated code to {code_path} (not executed)")
    else:
        print("no ```python block found in the answer content")

    # 2. Image prompt -> shape description
    image_response = client.chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": IMAGE_PROMPT},
                    {"type": "image_url", "image_url": {"url": image_data_url(IMAGE_PATH)}},
                ],
            }
        ],
    )
    report("image", image_response)


if __name__ == "__main__":
    main()
