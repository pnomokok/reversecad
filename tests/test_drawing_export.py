"""DXF and the 1:1 PDF template from a built part's profile; the PDF's 100 mm line must be 100 mm."""
import io
import re
import zlib

import ezdxf
import pytest
from fastapi.testclient import TestClient

from drawing_export import CHECK_LINE_MM, MARGIN_MM, dxf_bytes, page_for, template_pdf
from webapp import replay
from webapp.server import app

client = TestClient(app)
PLATE = {"outline": [[-40, -20], [40, -20], [40, 20], [-40, 20]], "thickness": 3.0, "box": [-40, -20, 40, 20],
         "holes": [{"type": "circle", "center": [-32, -12], "diameter": 6.0},
                   {"type": "polyline", "points": [[0, 0], [10, 0], [10, 5], [0, 5]]}]}
POINTS_PER_MM = 72 / 25.4


def test_dxf_has_the_outline_and_holes_in_mm_from_the_corner():
    document = ezdxf.read(io.StringIO(dxf_bytes(PLATE).decode("utf-8")))
    assert document.header["$INSUNITS"] == 4
    space = document.modelspace()
    outline = [e for e in space.query("LWPOLYLINE") if e.dxf.layer == "CUT_OUTER"][0]
    xs, ys = zip(*[(x, y) for x, y, *_ in outline.get_points()])
    assert (min(xs), max(xs), min(ys), max(ys)) == (0, 80, 0, 40) and outline.closed
    circle = space.query("CIRCLE")[0]
    assert circle.dxf.radius == 3.0 and tuple(circle.dxf.center)[:2] == (8, 8)
    assert len([e for e in space.query("LWPOLYLINE") if e.dxf.layer == "CUT_INNER"]) == 1


def test_template_pdf_is_true_scale():
    pdf = template_pdf(PLATE, "plate")
    width, height = map(float, re.search(rb"/MediaBox \[\s*0 0 ([\d.]+) ([\d.]+)", pdf).groups())
    assert (width, height) == pytest.approx((210 * POINTS_PER_MM, 297 * POINTS_PER_MM), abs=0.01)  # A4
    content = b"".join(zlib.decompress(s) for s in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S)
                       if s[:1] == b"x")
    # The check line: from the left margin to 100 mm further, in points (1 mm = 72 / 25.4 pt).
    start, end = MARGIN_MM * POINTS_PER_MM, (MARGIN_MM + CHECK_LINE_MM) * POINTS_PER_MM
    lines = re.findall(rb"([\d.]+) ([\d.]+) m\s+([\d.]+) ([\d.]+) l", content)
    assert any(abs(float(x1) - start) < 0.01 and abs(float(x2) - end) < 0.01 and y1 == y2
               for x1, y1, x2, y2 in lines), "no horizontal 100 mm line found in the page content"


def test_page_grows_with_the_part_and_refuses_what_does_not_fit():
    assert page_for(PLATE)[0] == "A4"
    wide = {**PLATE, "box": [0, 0, 300, 100]}  # wider than A4 landscape (297 mm with no margins)
    assert page_for(wide)[0] == "A3"
    with pytest.raises(ValueError):
        page_for({**PLATE, "box": [0, 0, 500, 100]})


@pytest.mark.skipif("A_light" not in replay.list_runs(), reason="needs the saved run A_light")
def test_drawing_and_downloads_from_the_app():
    drawing = client.post("/api/runs/A_light/drawing", json={"parameters": {}}).json()
    profile = drawing["profile"]
    assert len(profile["holes"]) == 4 and all(h["type"] == "circle" for h in profile["holes"])
    assert profile["thickness"] == pytest.approx(3.0, abs=0.01)
    x0, y0, x1, y1 = profile["box"]
    assert (x1 - x0, y1 - y0) == pytest.approx((79.31, 40.26), abs=0.02)
    for format in ("dxf", "pdf", "zip"):
        response = client.post(f"/api/runs/A_light/download?format={format}", json={"parameters": {}})
        assert response.status_code == 200 and len(response.content) > 500, format
