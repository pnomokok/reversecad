"""Take screenshots of the web app with headless Microsoft Edge (for review and recordings).

Uses the page's deep link (?run=<name>&step=...), so no clicking is needed. The server must be
running on http://127.0.0.1:8000.

Run: .venv\\Scripts\\python.exe -m webapp.screenshot A_light capture measure search edit
"""
import subprocess
import sys
from pathlib import Path

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
OUT = Path("outputs") / "screenshots"
SIZE = "1600,1000"


def screenshot(run, step, wait_ms=20000):
    """step may carry slider changes for the edit screen: "edit&set=length:95"."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = (OUT / f"{run}_{step.split('&')[0]}{'_changed' if '&set=' in step else ''}.png").resolve()
    subprocess.run([str(EDGE), "--headless=new", "--disable-gpu-sandbox", "--use-angle=swiftshader",
                    "--enable-unsafe-swiftshader", "--hide-scrollbars", f"--window-size={SIZE}",
                    f"--virtual-time-budget={wait_ms}", f"--screenshot={path}",
                    f"http://127.0.0.1:8000/?run={run}&step={step}"],
                   check=True, capture_output=True, timeout=120)
    print(path)


if __name__ == "__main__":
    run_name, *steps = sys.argv[1:] or ["A_light", "capture"]
    for step_name in steps or ["capture"]:
        screenshot(run_name, step_name)
