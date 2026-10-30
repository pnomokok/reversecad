"""Every frontend .js file must parse as an ES module (as the browser loads it).

Plain `node --check file.js` is not enough: on a .js file it silently passes
files that mix `import` statements with a later syntax error (seen 2026-10-30:
an extra `)` in app.js passed `node --check` but broke the page). Checking a
copy with an .mjs suffix forces module parsing, which is what the browser does.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "webapp" / "static"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@needs_node
def test_frontend_js_parses_as_module(tmp_path):
    files = sorted(STATIC.glob("*.js"))
    assert files, "no frontend .js files found"
    for path in files:
        probe = tmp_path / f"{path.stem}.mjs"
        probe.write_bytes(path.read_bytes())  # .mjs forces module parsing; imports are not resolved
        check = subprocess.run(["node", "--check", str(probe)], capture_output=True, text=True)
        assert check.returncode == 0, f"{path.name}: {check.stderr.strip()}"
