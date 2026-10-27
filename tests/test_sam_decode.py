"""The fast SAM mask decoder (sam_decode.py) must give exactly the library's raster.

Quick tests run always: masks encoded by the library's own encoder, the smallest saved SAM
answers, and the fallback. The check over every saved SAM answer takes about 5 minutes (the
library is the slow part), so it runs only with FULL_SAM_CHECK=1.
"""
import os
from pathlib import Path

import numpy as np
import pytest
from meta_sam_parser import CompletedOutcome, SegmentationMaskRecord, decode_mask_to_raster, image_segmentation_format
from meta_sam_parser._mask_codec import _encode_raster
from meta_sam_parser._types import SegmentationMask

import sam_decode

SAVED_ROOTS = ("outputs", "samples", "data/private")
sam_decode.use_in_parser()  # parse saved answers quickly; comparisons below call the library directly


def saved_masks(smallest_files=None):
    """(file, mask) for every mask in the saved raw SAM answers on this machine (or the smallest files)."""
    paths = sorted((p for root in SAVED_ROOTS for p in Path(root).rglob("*.txt")), key=lambda p: p.stat().st_size)
    answers = [(p, text) for p in paths if "<|mask" in (text := p.read_text(errors="ignore"))]
    found = []
    for path, text in answers[:smallest_files]:
        parser = image_segmentation_format().create_parser()
        parser.push(text)
        records = parser.finish(CompletedOutcome()).result.records
        found += [(path, r.mask) for r in records if isinstance(r, SegmentationMaskRecord)]
    return found


def one_bit(bits, width, height):
    return SegmentationMask(encoding="one_bit", width=width, height=height,
                            payload=_encode_raster(bits, width, height))


def test_matches_library_on_encoded_masks():
    rng = np.random.default_rng(0)
    yy, xx = np.mgrid[:57, :83]
    cases = [
        np.zeros((1, 1), np.uint8), np.ones((1, 1), np.uint8),   # single pixel
        np.ones((3, 1), np.uint8), np.ones((1, 5), np.uint8),    # one column, one row
        np.ones((40, 40), np.uint8),                             # all set: counts get halved often
        (rng.random((31, 47)) < 0.5).astype(np.uint8),           # noise: worst case for the coder
        ((xx - 40) ** 2 + (yy - 28) ** 2 < 400).astype(np.uint8),  # a disc, like a real mask
    ]
    for raster in cases:
        height, width = raster.shape
        mask = one_bit(raster.ravel().tolist(), width, height)
        assert sam_decode.fast_decode(mask.payload, width, height) == decode_mask_to_raster(mask)


def test_matches_library_on_smallest_saved_answers():
    masks = saved_masks(smallest_files=5)
    if not masks:
        pytest.skip("no saved SAM answers on this machine")
    for path, mask in masks:
        assert sam_decode.fast_decode(mask.payload, mask.width, mask.height) == decode_mask_to_raster(mask), path


@pytest.mark.skipif(not os.getenv("FULL_SAM_CHECK"), reason="about 4 minutes; set FULL_SAM_CHECK=1")
def test_matches_library_on_every_saved_answer():
    masks = saved_masks()
    assert masks
    for path, mask in masks:
        assert sam_decode.fast_decode(mask.payload, mask.width, mask.height) == decode_mask_to_raster(mask), path


def test_fast_path_refuses_what_it_cannot_decode():
    rng = np.random.default_rng(1)
    good = one_bit((rng.random(400) < 0.5).astype(np.uint8).tolist(), 20, 20)
    with pytest.raises(sam_decode.FastDecodeError):
        sam_decode.fast_decode(good.payload, 20, 40)  # wrong size: the payload runs out
    with pytest.raises(sam_decode.FastDecodeError):
        sam_decode.fast_decode(good.payload, 20, 5)  # wrong size: bytes left over
    with pytest.raises(sam_decode.FastDecodeError):
        sam_decode.fast_decode("~" + good.payload[1:], 20, 20)  # not one_bit
    with pytest.raises(sam_decode.FastDecodeError):
        sam_decode.fast_decode("!" + good.payload[1:-1] + "|", 20, 20)  # invalid character


def test_falls_back_to_the_library(monkeypatch):
    raster = [1, 0, 1, 1, 0, 0]
    mask = one_bit(raster, 3, 2)

    def refuse(*_):
        raise sam_decode.FastDecodeError("forced")

    monkeypatch.setattr(sam_decode, "fast_decode", refuse)
    assert sam_decode.decode_mask_to_raster(mask) == bytes(raster)
    # Encodings the fast path does not handle go straight to the library, errors included.
    lossless = SegmentationMask(encoding="lossless", width=3, height=2, payload="~bad")
    with pytest.raises(Exception) as fast_error:
        sam_decode.decode_mask_to_raster(lossless)
    with pytest.raises(Exception) as library_error:
        decode_mask_to_raster(lossless)
    assert type(fast_error.value) is type(library_error.value)
