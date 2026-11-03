"""Hole-label candidate spots cover the angles between compass points.

The capture overlay tries label spots on rings around each hole (group). Eight
compass points alone quantize to 45 degrees and can miss the only valid spot —
a shared "2x" label just inside a tilted part edge sits between grid points —
so ringSpots also tries the 8 half-offset angles, compass points first.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"
PROBE = Path(__file__).resolve().parent / "ringspots_probe.mjs"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_ringspots_tries_half_offset_angles():
    check = subprocess.run(["node", str(PROBE), str(STATIC / "app.js")],
                           capture_output=True, text=True)
    assert check.returncode == 0, check.stderr.strip() or check.stdout.strip()
