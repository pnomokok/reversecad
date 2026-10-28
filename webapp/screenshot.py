"""Take screenshots of the web app with Playwright, driving the installed Microsoft Edge (no browser download).

Uses the page's deep link (?run=<name>&step=...), so no clicking is needed, and waits until the page
says it is ready. The server must be running on http://127.0.0.1:8000. With --compare, each shot is
also put side by side with the matching design reference (design/<screen>/<screen>.png).

Run: .venv\\Scripts\\python.exe -m webapp.screenshot A_light capture measure search edit "edit&set=length:95"
     .venv\\Scripts\\python.exe -m webapp.screenshot --compare A_light measure search edit
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

OUT = Path("outputs") / "screenshots"
SIZE = {"width": 1440, "height": 900}
DESIGN = {"capture": "capture", "measure": "capture", "search": "search", "edit": "edit", "export": "export"}


def shot_path(run, step):
    """step may carry slider changes for the edit screen: "edit&set=length:95"."""
    return OUT / f"{run}_{step.split('&')[0]}{'_changed' if '&set=' in step else ''}.png"


def side_by_side(app_path, step, design_name=None):
    """The app's screenshot next to the design reference, both scaled to the same height."""
    design_name = design_name or DESIGN[step.split("&")[0]]
    design = Image.open(Path("design") / design_name / f"{design_name}.png").convert("RGB")
    app = Image.open(app_path).convert("RGB")
    height = 900
    design = design.resize((round(design.width * height / design.height), height))
    app = app.resize((round(app.width * height / app.height), height))
    sheet = Image.new("RGB", (app.width + design.width + 24, height + 40), (14, 14, 14))
    sheet.paste(app, (0, 40))
    sheet.paste(design, (app.width + 24, 40))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 12), "APP (1440 x 900)", fill=(255, 255, 255))
    draw.text((app.width + 34, 12), "DESIGN REFERENCE", fill=(255, 255, 255))
    path = app_path.with_name(app_path.stem + "_vs_design.png")
    sheet.save(path)
    return path


def main(arguments):
    compare = "--compare" in arguments
    design_name = next((a.split("=", 1)[1] for a in arguments if a.startswith("--design=")), None)
    arguments = [a for a in arguments if not a.startswith("--")]
    run, *steps = arguments or ["A_light", "capture"]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport=SIZE)
        for step in steps or ["capture"]:
            page.goto(f"http://127.0.0.1:8000/?run={run}&step={step}")
            page.wait_for_function("document.body.dataset.ready === 'true'", timeout=120_000)
            page.wait_for_timeout(1500)  # fonts, images and the 3D view settle
            path = shot_path(run, step)
            page.screenshot(path=str(path))
            print(path)
            if compare:
                print(side_by_side(path, step, design_name))
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
