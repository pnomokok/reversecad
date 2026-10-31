"""Camera-tilt warning: trapezoid metric, message text, and the measurements-screen field."""
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

import tilt_warning
from webapp import replay
from webapp.server import app

SAMPLES = ["A_light", "A_light_repair", "A_torn_fallback", "D_tab_broken"]
WARNING_TEXT = "Phone looks tilted \u2014 hold it parallel to the table and retake."

# Local private runs of the two real cardboard photos (never committed); the test using
# them skips itself on machines without them.
TILTED_MASK = Path("outputs/e2e/live-20261031-161042-2ab58f/3_mask_card.png")
PARALLEL_MASK = Path("outputs/e2e/live-20261031-163850-973a0e/3_mask_card.png")
TILTED_PHOTO = Path("data/private/real/IMG20261031160920.jpg")
PARALLEL_PHOTO = Path("data/private/real/IMG20261031163648.jpg")


def _card_mask(name):
    return cv2.imread(str(replay.SAMPLES_DIR / name / "3_mask_card.png"), cv2.IMREAD_GRAYSCALE) > 0


def test_saved_samples_show_no_warning():
    """Every sample's card is rectangular enough, so the demo stays warning-free."""
    for name in SAMPLES:
        tilt = tilt_warning.card_tilt(_card_mask(name))
        assert tilt <= tilt_warning.TILT_WARNING_THRESHOLD, name
        assert tilt_warning.tilt_warning(tilt) is None, name


def test_perspective_warped_card_warns():
    """A sample card warped like a tilted shot triggers the exact warning text."""
    full = _card_mask("A_light")
    assert tilt_warning.card_tilt(full) <= tilt_warning.TILT_WARNING_THRESHOLD
    ys, xs = np.nonzero(full)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    source = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    shift = 0.06 * (x1 - x0)  # one corner pushed in, like a phone held at an angle
    target = source + np.float32([[shift, 0], [0, 0], [0, 0], [0, 0]])
    warped = cv2.warpPerspective(full.astype("uint8"), cv2.getPerspectiveTransform(source, target),
                                 (full.shape[1], full.shape[0]), flags=cv2.INTER_NEAREST) > 0
    tilt = tilt_warning.card_tilt(warped)
    assert tilt > tilt_warning.TILT_WARNING_THRESHOLD
    assert tilt == pytest.approx(0.06, abs=0.02)
    assert tilt_warning.tilt_warning(tilt) == WARNING_TEXT


def test_warning_boundary():
    assert tilt_warning.tilt_warning(0.02) is None
    assert tilt_warning.tilt_warning(0.0201) == WARNING_TEXT


def test_analysis_carries_the_warning():
    """The measurements screen data includes the warning (live mode sends the same event)."""
    assert replay.analysis("A_light")["tilt_warning"] is None
    body = TestClient(app).get("/api/runs/A_light/analysis").json()
    assert body["tilt_warning"] is None
    assert body["card_tilt_pct"] < tilt_warning.TILT_WARNING_THRESHOLD * 100


@pytest.mark.skipif(not (TILTED_PHOTO.exists() and PARALLEL_PHOTO.exists()
                         and TILTED_MASK.exists() and PARALLEL_MASK.exists()),
                    reason="private real-photo runs are not on this machine")
def test_real_photos_tilted_warns_parallel_does_not():
    """The tilted phone shot warns, the parallel one does not (local private runs only)."""
    tilted = tilt_warning.card_tilt(cv2.imread(str(TILTED_MASK), cv2.IMREAD_GRAYSCALE) > 0)
    parallel = tilt_warning.card_tilt(cv2.imread(str(PARALLEL_MASK), cv2.IMREAD_GRAYSCALE) > 0)
    assert tilted > tilt_warning.TILT_WARNING_THRESHOLD
    assert parallel <= tilt_warning.TILT_WARNING_THRESHOLD
    assert tilt_warning.tilt_warning(tilted) == WARNING_TEXT
    assert tilt_warning.tilt_warning(parallel) is None
