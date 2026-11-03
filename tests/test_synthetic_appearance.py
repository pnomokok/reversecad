"""Painted surface appearances: the legacy look is frozen, new looks differ only on the part.

The legacy default (flat color plus brushed streaks) is pinned by hash: existing
scenes and the color-method tests depend on its exact bytes. Each appearance is
deterministic per seed, keeps the geometric masks identical, and changes photo
pixels only inside the part's region (background, card, tilt, blur and noise are
shared with the default scene).
"""
import hashlib

import cv2
import numpy as np
import pytest

from parts.template_parts import make_part
from synthetic_appearance import APPEARANCES
from synthetic_scene import DARK_PART, LIGHT_METAL, make_scene

LEGACY_HASHES = {"light": "ac62ad9d8a54ef84", "dark": "862a173375ea397e"}


def _digest(photo):
    return hashlib.sha256(photo.tobytes()).hexdigest()[:16]


@pytest.mark.parametrize("color", [LIGHT_METAL, DARK_PART], ids=["light", "dark"])
def test_legacy_default_is_bit_identical(color):
    photo, _ = make_scene(make_part("A"), color)
    assert _digest(photo) == LEGACY_HASHES["light" if color == LIGHT_METAL else "dark"]


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_appearance_is_deterministic(appearance):
    first, _ = make_scene(make_part("A"), appearance=appearance)
    second, _ = make_scene(make_part("A"), appearance=appearance)
    assert _digest(first) == _digest(second)


@pytest.mark.parametrize("appearance", APPEARANCES)
def test_appearance_changes_only_the_part_surface(appearance):
    workplane = make_part("A")
    photo, masks = make_scene(workplane, appearance=appearance)
    default, default_masks = make_scene(workplane, LIGHT_METAL)
    assert all(np.array_equal(masks[name], default_masks[name]) for name in ("card", "part"))
    spread = cv2.dilate(masks["part"].astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
    assert np.array_equal(photo[~spread], default[~spread])  # background, card and noise shared
    assert not np.array_equal(photo[masks["part"]], default[masks["part"]])  # but the surface differs


def test_unknown_appearance_raises():
    with pytest.raises(ValueError):
        make_scene(make_part("A"), appearance="marble")
