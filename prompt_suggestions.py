"""Ask Muse Spark Open for SAM text prompts that name the part in a photo.

SAM needs a short English noun phrase, and the right one depends on the part
("plate" found nothing on the synthetic plate, "metal plate" did). The model
looks at the photo and suggests 3-4 phrases; all are tried and the most
confident SAM mask wins.
"""
import json
import re

from baseten_client import MODEL, image_data_url, make_client

MAX_TOKENS = 6000  # reasoning tokens count toward this limit
MAX_PROMPTS = 4

INSTRUCTION = (
    "The photo shows a reference card and one other object lying on a table. "
    "Suggest 3 or 4 short English noun phrases (1 to 3 words each) that name the other object, not the card, "
    "to be used as text prompts for an image segmentation model. Most specific first. "
    "Reply with only a JSON array of strings."
)


def parse_prompts(text):
    """Pull a JSON list of short strings out of the model's answer."""
    match = re.search(r"\[.*?\]", text or "", re.DOTALL)
    if not match:
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    prompts = []
    for item in items:
        if isinstance(item, str) and 0 < len(item.split()) <= 4 and item.strip().lower() not in prompts:
            prompts.append(item.strip().lower())
    return prompts[:MAX_PROMPTS]


def suggest_part_prompts(photo_path):
    """Return (prompts, raw answer text)."""
    response = make_client().chat.completions.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": INSTRUCTION},
                {"type": "image_url", "image_url": {"url": image_data_url(photo_path)}},
            ],
        }],
    )
    content = response.choices[0].message.content
    return parse_prompts(content), content
