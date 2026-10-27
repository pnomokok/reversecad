"""Call SAM 3.1 on the Meta Model API and return full-size masks.

One prompt per request: a short English noun phrase, or a point prompt
(point_prompt) that selects the object under a clicked pixel. Photos are
EXIF-transposed first, so SAM's coordinates match the image as displayed,
and re-encoded in memory, which also drops EXIF data from what is sent.
The API key is read from MODEL_API_KEY in .env.
"""
import base64
import io
import os
from dataclasses import dataclass

import cv2
import numpy as np
from dotenv import load_dotenv
from meta_sam_parser import (
    CompletedOutcome,
    FramePrompt,
    PromptObject,
    PromptPoint,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    build_object_prompt,
    decode_mask_to_raster,
    image_segmentation_format,
)
from openai import OpenAI
from PIL import Image, ImageOps

BASE_URL = "https://api.meta.ai/v1"
MODEL = "sam-3.1"


@dataclass
class Detection:
    object_id: str
    confidence: float | None
    box: tuple  # (left, top, right, bottom) in photo pixels, right/bottom exclusive
    mask: np.ndarray  # bool, same size as the photo
    mask_size: tuple  # (width, height) of the raster SAM sent, before placement


def make_client():
    load_dotenv()
    api_key = os.getenv("MODEL_API_KEY")
    if not api_key:
        raise RuntimeError("MODEL_API_KEY is missing from .env")
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def load_photo(path):
    """Open a photo upright (EXIF orientation applied) as RGB."""
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _jpeg_data_url(image):
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)  # no exif= argument, so no EXIF is written
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _stream_text(stream):
    """Collect the output text from a Responses API event stream."""
    deltas, final_text = [], None
    for event in stream:
        if event.type == "response.output_text.delta":
            deltas.append(event.delta)
        elif event.type == "response.content_part.done" and getattr(event.part, "type", None) == "output_text":
            final_text = event.part.text
    return final_text if final_text is not None else "".join(deltas)


def point_prompt(image_size, x, y):
    """Object prompt text that selects whatever lies under pixel (x, y), like a user's click."""
    point = PromptPoint(int(round(x)), int(round(y)))
    return build_object_prompt(size=image_size, objects=[PromptObject(id=1, prompts=[FramePrompt(points=[point])])])


def segment(client, image, prompt):
    """Return (detections, raw_text) for one noun-phrase prompt; empty list if nothing matched.

    image is a PIL image (see load_photo).
    """
    stream = client.responses.create(
        model=MODEL,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _jpeg_data_url(image)},
                ],
            }
        ],
        stream=True,
        metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
    )
    raw_text = _stream_text(stream)
    return parse_detections(raw_text, image.size), raw_text


def parse_detections(raw_text, image_size):
    """Turn raw SAM output text into Detections; also works on saved raw files."""
    parser = image_segmentation_format().create_parser()
    parser.push(raw_text)
    result = parser.finish(CompletedOutcome()).result

    boxes = {r.object_id: r for r in result.records if isinstance(r, SegmentationBoxRecord)}
    detections = []
    for record in result.records:
        if not isinstance(record, SegmentationMaskRecord):
            continue
        box = boxes.get(record.object_id)
        box_edges = (box.left, box.top, box.right, box.bottom) if box else None
        confidence = record.confidence if record.confidence is not None else getattr(box, "confidence", None)
        detections.append(
            Detection(
                object_id=record.object_id,
                confidence=confidence,
                box=box_edges,
                mask=_place_mask(record, image_size),
                mask_size=(record.mask.width, record.mask.height),
            )
        )
    return detections


def _place_mask(record, image_size):
    raster = np.frombuffer(decode_mask_to_raster(record.mask), dtype=np.uint8)
    local = raster.reshape(record.mask.height, record.mask.width).astype(bool)
    bounds = (record.bounds.left, record.bounds.top, record.bounds.right, record.bounds.bottom)
    return place_mask(local, bounds, image_size)


def place_mask(local, bounds, image_size):
    """Put SAM's box-local raster into a full-size boolean mask at its bounds.

    SAM caps the raster's long side (1024 px seen), so masks of large objects
    arrive downscaled; they are scaled back up to the box size first.
    """
    width, height = image_size
    left, top = int(round(bounds[0])), int(round(bounds[1]))
    box_width, box_height = int(round(bounds[2])) - left, int(round(bounds[3])) - top
    if local.shape != (box_height, box_width):
        resized = cv2.resize(local.astype(np.float32), (box_width, box_height), interpolation=cv2.INTER_LINEAR)
        local = resized >= 0.5

    full = np.zeros((height, width), dtype=bool)
    bottom, right = min(top + local.shape[0], height), min(left + local.shape[1], width)
    full[top:bottom, left:right] = local[: bottom - top, : right - left]
    return full
