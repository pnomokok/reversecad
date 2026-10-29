"""Low-resolution card warning: pixel length, message text, and the measurements-screen field."""
import cv2
import pytest
from fastapi.testclient import TestClient

import resolution
from webapp import replay
from webapp.server import app

SAMPLES = ["A_light", "A_light_repair", "A_torn_fallback", "D_tab_broken"]


def _card_mask(name):
    return cv2.imread(str(replay.SAMPLES_DIR / name / "3_mask_card.png"), cv2.IMREAD_GRAYSCALE) > 0


def test_saved_samples_show_no_warning():
    """Every sample's card clears the threshold, so the demo stays warning-free."""
    for name in SAMPLES:
        px = resolution.card_long_edge_px(_card_mask(name))
        assert px >= resolution.MIN_CARD_PX, name
        assert resolution.resolution_warning(px) is None, name


def test_downscaled_sample_image_warns():
    """A sample card shrunk like a messenger photo triggers the exact warning text."""
    full = _card_mask("A_light")
    full_px = resolution.card_long_edge_px(full)
    small = cv2.resize(full.astype("uint8"), None, fx=0.5, fy=0.5,
                       interpolation=cv2.INTER_NEAREST) > 0
    px = resolution.card_long_edge_px(small)
    assert px < resolution.MIN_CARD_PX
    assert px == pytest.approx(full_px / 2, abs=3)
    assert resolution.resolution_warning(px) == (
        f"The card is only {px:.0f} px long, so small holes and edges lose precision. "
        "Send the photo at original quality (messenger apps shrink photos).")


def test_warning_boundary():
    assert resolution.resolution_warning(600) is None
    assert resolution.resolution_warning(599.9).startswith("The card is only 600 px long")


def test_analysis_carries_the_warning():
    """The measurements screen data includes the warning (live mode sends the same event)."""
    assert replay.analysis("A_light")["resolution_warning"] is None
    body = TestClient(app).get("/api/runs/A_light/analysis").json()
    assert body["resolution_warning"] is None
    assert body["card_long_px"] >= resolution.MIN_CARD_PX
