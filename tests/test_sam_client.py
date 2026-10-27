"""Tests for placing SAM's box-local mask raster into the full photo (no API calls)."""
import numpy as np

from sam_client import place_mask, point_prompt


def test_point_prompt_selects_a_pixel():
    assert point_prompt((2048, 1536), 1500.4, 700.6) == "<0f>1<|point;x=1500;y=701;w=2048;h=1536|>"


def test_full_size_raster_is_placed_at_box_corner():
    local = np.ones((30, 20), dtype=bool)
    full = place_mask(local, (100, 50, 120, 80), (300, 200))
    ys, xs = full.nonzero()
    assert (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) == (100, 50, 120, 80)


def test_downscaled_raster_is_stretched_to_box_size():
    # SAM sends a smaller raster for large objects; it must still cover the whole box.
    local = np.ones((512, 325), dtype=bool)
    full = place_mask(local, (366, 121, 1116, 1302), (2048, 1536))
    ys, xs = full.nonzero()
    assert (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) == (366, 121, 1116, 1302)
    assert full.sum() == 750 * 1181
