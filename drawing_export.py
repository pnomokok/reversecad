"""2D outputs from a part's top-face profile (build_worker.profile): DXF for laser cutting, and a PDF
template printed at true scale (1:1) with a 100 mm line to check the printer's scale.

The profile is in mm: {"outline": [[x, y], ...], "holes": [{"type": "circle", "center", "diameter"} or
{"type": "polyline", "points"}], "thickness", "box": [x_min, y_min, x_max, y_max]}.
"""
import io
import time

import ezdxf
import matplotlib

matplotlib.use("Agg")  # no window: files only
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Polygon  # noqa: E402

PAGES = {"A4": (210.0, 297.0), "A3": (297.0, 420.0)}  # portrait width x height, mm
MARGIN_MM = 15.0
FOOTER_MM = 32.0  # room under the part for the 100 mm line and the notes
CHECK_LINE_MM = 100.0


def dxf_bytes(profile, name="part"):
    """The outline and the holes as closed 2D contours (layers CUT_OUTER, CUT_INNER), in mm, origin at the
    bounding box's lower-left corner."""
    x0, y0 = profile["box"][0], profile["box"][1]
    shift = lambda points: [(x - x0, y - y0) for x, y in points]  # noqa: E731
    document = ezdxf.new("R2010", setup=True)
    document.header["$INSUNITS"] = 4  # millimeters
    document.layers.add("CUT_OUTER", color=7)
    document.layers.add("CUT_INNER", color=1)
    space = document.modelspace()
    space.add_lwpolyline(shift(profile["outline"]), close=True, dxfattribs={"layer": "CUT_OUTER"})
    for hole in profile["holes"]:
        if hole["type"] == "circle":
            (x, y), = shift([hole["center"]])
            space.add_circle((x, y), hole["diameter"] / 2, dxfattribs={"layer": "CUT_INNER"})
        else:
            space.add_lwpolyline(shift(hole["points"]), close=True, dxfattribs={"layer": "CUT_INNER"})
    document.header["$PROJECTNAME"] = name[:60]
    stream = io.StringIO()
    document.write(stream)
    return stream.getvalue().encode("utf-8")


def page_for(profile):
    """The smallest page (A4 or A3, either orientation) that holds the part, the margins and the footer."""
    x0, y0, x1, y1 = profile["box"]
    need = (x1 - x0 + 2 * MARGIN_MM, y1 - y0 + 2 * MARGIN_MM + FOOTER_MM)
    for name, (width, height) in PAGES.items():
        for size in ((width, height), (height, width)):
            if need[0] <= size[0] and need[1] <= size[1] and size[0] >= CHECK_LINE_MM + 2 * MARGIN_MM:
                return name, size
    raise ValueError(f"the part ({x1 - x0:.0f} x {y1 - y0:.0f} mm) is larger than an A3 page")


def template_pdf(profile, name="part"):
    """A one-page PDF with the part's outline and holes at 1:1 and a 100 mm line to check the scale."""
    page, (width, height) = page_for(profile)
    x0, y0, x1, y1 = profile["box"]
    figure = plt.figure(figsize=(width / 25.4, height / 25.4))
    axes = figure.add_axes([0, 0, 1, 1])  # the whole page, 1 unit = 1 mm
    axes.set_xlim(0, width)
    axes.set_ylim(0, height)
    axes.set_aspect("equal")
    axes.axis("off")
    # The part, centered in the space above the footer.
    dx = (width - (x1 - x0)) / 2 - x0
    dy = FOOTER_MM + (height - FOOTER_MM - (y1 - y0)) / 2 - y0
    line = 0.25  # points; thin, so it can be cut along
    axes.add_patch(Polygon([(x + dx, y + dy) for x, y in profile["outline"]], closed=True, fill=False,
                           linewidth=line, edgecolor="black"))
    for hole in profile["holes"]:
        if hole["type"] == "circle":
            cx, cy = hole["center"][0] + dx, hole["center"][1] + dy
            radius = hole["diameter"] / 2
            axes.add_patch(Circle((cx, cy), radius, fill=False, linewidth=line, edgecolor="black"))
            mark = radius + 2  # center mark for a drill or a punch
            axes.plot([cx - mark, cx + mark], [cy, cy], color="black", linewidth=0.15)
            axes.plot([cx, cx], [cy - mark, cy + mark], color="black", linewidth=0.15)
        else:
            axes.add_patch(Polygon([(x + dx, y + dy) for x, y in hole["points"]], closed=True, fill=False,
                                   linewidth=line, edgecolor="black"))
    # The 100 mm check line with 10 mm ticks.
    left, base = MARGIN_MM, MARGIN_MM + 8
    axes.plot([left, left + CHECK_LINE_MM], [base, base], color="black", linewidth=0.8)
    for i in range(11):
        tick = 3 if i % 5 == 0 else 1.5
        axes.plot([left + 10 * i, left + 10 * i], [base, base + tick], color="black", linewidth=0.5)
    axes.text(left, base - 5, f"{CHECK_LINE_MM:.0f} mm: measure this line; if it is not exactly {CHECK_LINE_MM:.0f} mm, "
              "the print is not to scale.", fontsize=7, va="center")
    axes.text(left, base + 8, "Print at 100% / actual size (not 'fit to page').", fontsize=7, va="center")
    axes.text(width - MARGIN_MM, base + 8, f"{name}  ·  scale 1:1  ·  units mm  ·  {page}", fontsize=7,
              va="center", ha="right")
    axes.text(width - MARGIN_MM, base - 5, f"{x1 - x0:.2f} x {y1 - y0:.2f} mm, {profile['thickness']:.2f} mm thick  ·  "
              f"{time.strftime('%Y-%m-%d')}", fontsize=7, va="center", ha="right")
    stream = io.BytesIO()
    figure.savefig(stream, format="pdf")  # no bbox cropping: the page keeps its exact size
    plt.close(figure)
    return stream.getvalue()
