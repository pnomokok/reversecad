// ReverseCAD front end. Three screens (layout adapted from the Stitch screens in design/):
//   Capture: upload a photo or try an example, click the part, set the thickness, measure.
//   Search:  candidates arrive one by one (server-sent events) into a grid; the selected one grows to 2×2.
//   Edit:    the result in 3D with dimension labels, a slider per named parameter, and downloads.
// Every number shown comes from the back end or from the built model; nothing is made up for display.
// ?run=<name>&step=capture|measure|search|edit opens a saved run on that screen (screenshots, videos);
// with step=edit, &set=<parameter>:<value>,... also moves sliders; with step=edit or export, &match=cover|spacer
// opens that matching part first.
import { createViewer } from "./viewer.js";
import { showParts } from "./parts.js";

const state = {
  screen: "capture", run: null, live: false, image: null, click: null, analysis: null,
  stream: null, viewer: null, winner: null, done: null, seen: [], expected: null,
  matching: null,  // the matching part on screen: {kind, base: the original's slider values}; winner then describes it
  splitWarning: null,  // gasket split warning text while a spacer offset breaks the part in pieces
  builds: 0,  // counts model builds; see rebuild
};
const $ = (id) => document.getElementById(id);
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const canvas = $("photo-canvas");
const context = canvas.getContext("2d");

// Completion answers for sample runs live in this browser only (the server never writes them for samples):
// stored here and sent with every request, so each visitor of the shared demo has their own Apply/Ignore.
const decisionKey = (run) => `reversecad.completion.${run}`;
function storedDecision(run) {
  try {
    const text = run ? localStorage.getItem(decisionKey(run)) : null;
    return text ? JSON.parse(text) : null;
  } catch {
    return null;  // storage blocked or broken: no stored answer
  }
}
function storeDecision(run, answer) {
  try {
    if (answer && answer.decision) localStorage.setItem(decisionKey(run), JSON.stringify(answer));
    else localStorage.removeItem(decisionKey(run));
  } catch {
    // storage blocked (private window): the answer lasts until the next request without it
  }
}
function runHeaders() {
  const answer = storedDecision(state.run);
  return answer ? { "X-Completion-Decision": encodeURIComponent(JSON.stringify(answer)) } : {};
}

async function getJSON(url) {
  const response = await fetch(url, { headers: runHeaders() });
  if (!response.ok) throw new Error(`${url}: ${response.status} ${await response.text()}`);
  return response.json();
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = url;
  });
}

const pad2 = (n) => String(n).padStart(2, "0");
const idOf = (event) => event.label || pad2(event.candidate);  // repaired programs are R1, R2
const mm = (value, digits = 2) => `${Number(value).toFixed(digits)} mm`;

// ---------- screens ----------
function setScreen(screen) {
  // "match" is step 4: the edit screen with the Matching part tab (one source of truth for both).
  state.screen = screen;
  const section = screen === "match" ? "edit" : screen;
  document.querySelectorAll("#steps button, #rail button").forEach((b) => b.classList.toggle("active",
    b.dataset.screen === screen || (screen === "match" && b.dataset.screen === "edit" && b.closest("#rail"))));
  ["capture", "search", "edit", "export", "parts"].forEach((name) => $(`screen-${name}`).classList.toggle("hidden", name !== section));
  if (section === "edit") selectPanelTab(screen === "match" ? "matching" : "parameters");
  if (screen === "capture") render();
  if (section === "edit" && state.viewer) state.viewer.resize();
  updateHeader();
}

function selectPanelTab(tab) {
  // Instant show/hide only, so switching tabs keeps every slider value, input and verdict.
  document.querySelectorAll(".panel-tab-button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $("edit-panel").dataset.tab = tab;
}

document.querySelectorAll(".panel-tab-button").forEach((button) =>
  button.addEventListener("click", () => setScreen(button.dataset.tab === "matching" ? "match" : "edit")));

$("panel-wide").addEventListener("click", () => {
  const wide = $("edit-panel").classList.toggle("wide");
  $("panel-wide").title = wide ? "Narrow panel" : "Wide panel";
  if (state.viewer) state.viewer.resize();  // the 3D view and its labels follow the new width
});

function enableSteps() {
  const canEdit = !!(state.done && state.done.result_source && !state.done.result_source.startsWith("none"));
  document.querySelectorAll('[data-screen="search"]').forEach((b) => (b.disabled = !state.analysis));
  document.querySelectorAll('[data-screen="edit"], [data-screen="match"], [data-screen="export"]').forEach((b) => (b.disabled = !canEdit));
}

document.querySelectorAll("#steps button, #rail button").forEach((button) =>
  button.addEventListener("click", async () => {
    if (button.dataset.screen === "export") showExport();
    else if (button.dataset.screen === "edit" && !state.winner) showModel();
    else if (button.dataset.screen === "match" && !state.winner) { await showModel(); setScreen("match"); }
    else if (button.dataset.screen === "parts") openParts();
    else setScreen(button.dataset.screen);
  }));

function updateHeader() {
  const chip = $("run-chip");
  chip.classList.toggle("hidden", !state.run);
  // The kind of run: an upload in live mode is a real photo; a saved run says what it is.
  const kind = state.live ? "Real photo" : state.runKind === "Synthetic" ? (state.sample ? "Synthetic sample" : "Synthetic")
    : state.runKind || "";
  // The kind always shows in full; only the run name is shortened when the window is narrow.
  chip.innerHTML = state.run ? `${kind ? `<span class="run-kind">${esc(kind)} ·</span>` : ""}<span class="run-name">${esc(state.run)}</span>` : "";
  chip.title = chip.textContent;
  // Replay never calls a model: say so for as long as a saved run is on screen (live mode never shows it).
  $("replay-chip").classList.toggle("hidden", !state.run || state.live);
  const searching = state.screen === "search" && !!state.analysis;
  $("progress").classList.toggle("hidden", !searching);
  if (!searching) return;
  const total = state.done ? state.done.candidate_count : state.expected;
  const count = state.seen.filter((e) => !e.label).length;  // requested candidates only, not repairs (R1, R2)
  const repaired = state.done && (state.done.result_source || "").startsWith("repair");
  const finished = state.live ? "Search finished" : "Replay finished";
  $("progress-label").textContent = repaired ? `${finished} · repaired by Muse Wonder`
    : state.done ? `${finished} · Muse Spark Open`
    : state.live ? "Generating with Muse Spark Open · Checking against the SAM 3.1 mask" : "Replaying a saved candidate round";
  $("progress-count").textContent = total ? `${Math.round((100 * count) / total)}% | ${count} / ${total}` : `${count}`;
  $("progress-fill").style.width = total ? `${(100 * count) / total}%` : "0";
}

// Live stopwatch (header): ticks while a live stage runs; replay shows the run's recorded durations.
const watch = {
  elapsed: 0, since: null, timer: null,
  format(seconds) {
    const total = Math.max(0, Math.floor(seconds));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
  },
  show(text, title, ticking) {
    const el = $("stopwatch");
    el.classList.toggle("hidden", !text);
    el.classList.toggle("ticking", !!ticking);
    if (text) el.textContent = text;
    el.title = title || "";
  },
  current() { return this.elapsed + (this.since == null ? 0 : (performance.now() - this.since) / 1000); },
  tick() {
    clearInterval(this.timer);
    this.timer = setInterval(() => this.show(this.format(this.current()), "", true), 250);
    this.show(this.format(this.current()), "", true);
  },
  start() { this.elapsed = 0; this.since = performance.now(); this.tick(); },
  pause() {
    if (this.since == null) return;
    this.elapsed = this.current();
    this.since = null;
    clearInterval(this.timer);
    this.timer = null;
    this.show(this.format(this.elapsed), "", false);
  },
  resume() {
    if (!state.live || this.since != null) return;
    this.since = performance.now();
    this.tick();
  },
  finish(durations) {
    this.pause();
    const total = durations && durations.total_seconds;
    const search = durations && durations.search_seconds;
    if (state.live) {
      if (total != null) this.show(this.format(total), this.tip(durations), false);
      return;  // else the frozen client value stays: measured, never invented
    }
    // Replay: the run's own recorded durations; a run saved without them shows none (never invented).
    if (total != null) this.show(`Took ${this.format(total)}`, `Recorded: ${this.tip(durations)}`, false);
    else if (search != null) this.show(`Search took ${this.format(search)}`, "Recorded duration", false);
    else this.reset();
  },
  tip(durations) {
    const parts = [];
    if (durations.measure_seconds != null) parts.push(`measure ${this.format(durations.measure_seconds)}`);
    if (durations.search_seconds != null) parts.push(`search ${this.format(durations.search_seconds)}`);
    return parts.join(" · ");
  },
  reset() {
    clearInterval(this.timer);
    this.timer = null;
    this.elapsed = 0;
    this.since = null;
    this.show("", "", false);
  },
};

// ---------- capture: photo and overlay ----------
function scale() {
  return canvas.width / (canvas.clientWidth || canvas.width);
}

function polygon(points, color, width, closed = true, glow = false, progress = 1) {
  context.save();
  context.beginPath();
  const shown = progress >= 1 ? points : points.slice(0, Math.max(2, Math.ceil(points.length * progress)));
  shown.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
  if (closed && progress >= 1) context.closePath();
  context.strokeStyle = color;
  context.lineWidth = width * scale();
  if (glow) {
    context.shadowColor = css("--color-selected-glow");
    context.shadowBlur = 16 * scale();
  }
  context.stroke();
  context.restore();
}

function callout(text, x, y, fontPx = Number(css("--callout-font-px")), angle = 0) {
  // A dimension box: dark fill, white border, white monospace text, centered on (x, y); turned by
  // `angle` (radians) when it runs along a steep dimension line.
  const s = scale();
  context.save();
  context.translate(x, y);
  context.rotate(angle);
  context.font = `700 ${fontPx * s}px ${css("--font-mono")}`;
  const width = context.measureText(text).width + 16 * s;
  const height = fontPx * 1.6 * s;
  context.fillStyle = css("--color-callout-bg");
  context.fillRect(-width / 2, -height / 2, width, height);
  context.strokeStyle = css("--color-dimension");
  context.lineWidth = Number(css("--callout-border-px")) * s;
  context.strokeRect(-width / 2, -height / 2, width, height);
  context.fillStyle = css("--color-dimension");
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 0, 1 * s);
  context.restore();
}

function dimensionLine(x1, y1, x2, y2) {
  const s = scale();
  const tick = 10 * s;
  const length = Math.hypot(x2 - x1, y2 - y1) || 1;
  const [nx, ny] = [-(y2 - y1) / length, (x2 - x1) / length];  // across the line
  context.strokeStyle = css("--color-dimension");
  context.lineWidth = 2 * s;
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  for (const [x, y] of [[x1, y1], [x2, y2]]) {
    context.moveTo(x - nx * tick, y - ny * tick);
    context.lineTo(x + nx * tick, y + ny * tick);
  }
  context.stroke();
}

function convexHull(points) {
  // Monotone chain: the hull's corners in order.
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (list) => {
    const h = [];
    for (const p of list) {
      while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], p) <= 0) h.pop();
      h.push(p);
    }
    h.pop();
    return h;
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

function minAreaBox(points) {
  // The shape's minimum-area rectangle — the same box cv2.minAreaRect gives the measurement table,
  // so each drawn extent lies along the axis it was measured on. u is the long axis (length, pointing
  // right), v the short one (width, u turned +90°); range.u / range.v are the extents along them, as
  // plain projections (a point is u·a + v·b).
  const hull = convexHull(points);
  const span = (axis) => {
    const c = hull.map((h) => h[0] * axis[0] + h[1] * axis[1]);
    return [Math.min(...c), Math.max(...c)];
  };
  let best = null;
  for (let i = 0; i < hull.length; i++) {
    const [p, q] = [hull[i], hull[(i + 1) % hull.length]];
    const length = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (length < 1e-9) continue;
    const e = [(q[0] - p[0]) / length, (q[1] - p[1]) / length];
    const [se, sn] = [span(e), span([-e[1], e[0]])];
    const area = (se[1] - se[0]) * (sn[1] - sn[0]);
    if (!best || area < best.area) best = { area, e, long: se[1] - se[0] >= sn[1] - sn[0] };
  }
  let u = best.long ? best.e : [-best.e[1], best.e[0]];
  if (u[0] < 0 || (u[0] === 0 && u[1] < 0)) u = [-u[0], -u[1]];
  const v = [-u[1], u[0]];
  return { u, v, range: { u: span(u), v: span(v) } };
}

function extentGeometry(points, box, along, side, gap) {
  // One extent dimension of a shape. `along` is "u" (length) or "v" (width); `side` −1 or +1 picks the
  // shape's low or high side across it. The dimension line runs parallel to `along`, `gap` outside the
  // shape, between the two extreme points' projections; an extension line runs from each extreme point
  // (the one nearest this side, when several are extreme) to just past the dimension line.
  const s = scale();
  const across = along === "u" ? "v" : "u";
  const [m, c] = [box[along], box[across]];
  const [m0, m1] = box.range[along];
  const [c0, c1] = box.range[across];
  const coord = (p, axis) => p[0] * axis[0] + p[1] * axis[1];
  const at = (a, b) => [m[0] * a + c[0] * b, m[1] * a + c[1] * b];
  const line = side < 0 ? c0 - gap : c1 + gap;
  // Points this close to an extreme count as extreme too (a mask edge is never perfectly straight),
  // so the extension line starts at the extreme corner nearest this side, not across the shape.
  const [tol, startGap, past] = [Math.max(2, 0.02 * (m1 - m0)), 4 * s, 8 * s];
  const extension = (end) => {
    const extremes = points.filter((p) => Math.abs(coord(p, m) - end) <= tol).map((p) => coord(p, c));
    const from = side < 0 ? Math.min(...extremes) : Math.max(...extremes);
    return [at(end, from + side * startGap), at(end, line + side * past)];
  };
  return { a: at(m0, line), b: at(m1, line), ext: [extension(m0), extension(m1)] };
}

function preferredSide(box, along, avoidPolys) {
  // The side facing away from the first shape to avoid (the other object), across `along`.
  const axis = box[along === "u" ? "v" : "u"];
  const [c0, c1] = box.range[along === "u" ? "v" : "u"];
  if (!avoidPolys.length) return -1;
  const other = avoidPolys[0].reduce((t, p) => t + p[0] * axis[0] + p[1] * axis[1], 0) / avoidPolys[0].length;
  return other > (c0 + c1) / 2 ? -1 : 1;
}

let occupied = [];  // boxes of the labels drawn so far in this render: [left, top, right, bottom]
let placedLines = [];  // dimension and extension lines drawn so far: labels keep clear of them
let dimensionLines = [];  // the dimension lines alone: hole leaders may cross extension lines, not these

function labelBox(text, x, y, fontPx = Number(css("--callout-font-px")), angle = 0) {
  // The label's screen box [left, top, right, bottom]; for a turned label, the box around it.
  const s = scale();
  context.font = `700 ${fontPx * s}px ${css("--font-mono")}`;
  const [tw, th] = [context.measureText(text).width + 16 * s, fontPx * 1.6 * s];
  const [c, n] = [Math.abs(Math.cos(angle)), Math.abs(Math.sin(angle))];
  const [w, h] = [c * tw + n * th, n * tw + c * th];
  return [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
}

function fits(box, extra = []) {
  // Inside the photo, and clear of the labels placed so far plus any extra boxes (shapes to avoid).
  const pad = 4 * scale();
  const inPhoto = box[0] > 0 && box[1] > 0 && box[2] < canvas.width && box[3] < canvas.height;
  return inPhoto && ![...occupied, ...extra].some((o) => box[0] < o[2] + pad && box[2] > o[0] - pad && box[1] < o[3] + pad && box[3] > o[1] - pad);
}

function segsCross(p, q, r, s) {
  // Whether the segments p→q and r→s touch (touching counts).
  const dir = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return dir(p, q, r) * dir(p, q, s) <= 0 && dir(r, s, p) * dir(r, s, q) <= 0;
}

function segHitsBox(p, q, box) {
  // Whether the segment p→q touches the rectangle (keeps dimension lines and leaders off labels).
  const [left, top, right, bottom] = box;
  const inside = ([x, y]) => x >= left && x <= right && y >= top && y <= bottom;
  if (inside(p) || inside(q)) return true;
  const corners = [[left, top], [right, top], [right, bottom], [left, bottom]];
  return corners.some((c, i) => segsCross(p, q, c, corners[(i + 1) % 4]));
}

function lineFits(a, b, extra = []) {
  // Both ends inside the photo, and the line clear of placed labels plus any extra boxes.
  // Non-strict: stubs are clamped exactly onto this margin before scoring.
  const pad = 4 * scale();
  const inside = ([x, y]) => x >= pad && y >= pad && x <= canvas.width - pad && y <= canvas.height - pad;
  if (!inside(a) || !inside(b)) return false;
  return ![...occupied, ...extra].some((o) => segHitsBox(a, b, [o[0] - pad, o[1] - pad, o[2] + pad, o[3] + pad]));
}

function pointInPoly([x, y], poly) {
  // Ray casting: an odd number of edge crossings to the right means inside.
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function segHitsPoly(p, q, poly) {
  // Whether the segment p→q touches the polygon (an end inside, or an edge crossed).
  if (pointInPoly(p, poly) || pointInPoly(q, poly)) return true;
  return segCrossesPoly(p, q, poly);
}

function segCrossesPoly(p, q, poly) {
  // Whether the segment crosses the polygon's boundary (ends inside do not count: a leader
  // from an inside label to an inside hole is clean unless it leaves through a notch).
  return poly.some((c, i) => segsCross(p, q, c, poly[(i + 1) % poly.length]));
}

function boxHitsPoly(box, poly) {
  // Whether the rectangle touches the polygon (a corner or the center inside, or an edge crossed).
  const [l, t, r, b] = box;
  if ([[l, t], [r, t], [r, b], [l, b], [(l + r) / 2, (t + b) / 2]].some((p) => pointInPoly(p, poly))) return true;
  return poly.some((c, i) => segHitsBox(c, poly[(i + 1) % poly.length], box));
}

function labelFits(box, avoidPolys, turned = null) {
  // Inside the photo, clear of placed labels and dimension lines, and off every avoided shape. A
  // turned label (`turned`: its four corners) is checked against shapes and lines by its own
  // rectangle, not the larger screen box around it.
  if (!fits(box)) return false;
  if (turned) {
    if (avoidPolys.some((poly) => polysTouch(turned, poly))) return false;
    return !placedLines.some(([a, b]) => segHitsPoly(a, b, turned));
  }
  if (avoidPolys.some((poly) => boxHitsPoly(box, poly))) return false;
  return !placedLines.some(([a, b]) => segHitsBox(a, b, box));
}

function polysTouch(p, q) {
  // Whether two polygons overlap: a corner of one inside the other, or two edges crossing.
  if (p.some((pt) => pointInPoly(pt, q)) || q.some((pt) => pointInPoly(pt, p))) return true;
  return p.some((c, i) => segCrossesPoly(c, p[(i + 1) % p.length], q));
}

function labelCorners(text, [x, y], angle, fontPx = Number(css("--callout-font-px"))) {
  // The four corners of a label turned by `angle` around its center.
  const [halfW, halfH] = labelBox(text, 0, 0, fontPx).slice(2);
  const [c, n] = [Math.cos(angle), Math.sin(angle)];
  return [[-halfW, -halfH], [halfW, -halfH], [halfW, halfH], [-halfW, halfH]]
    .map(([dx, dy]) => [x + dx * c - dy * n, y + dx * n + dy * c]);
}

function extentDimension(points, along, text, ownPoly, avoidPolys) {
  // One extent of a shape, drawn parallel to the axis it measures, just outside the shape: first on
  // the side facing away from the other object — with an upright label, then, for a steep line, with
  // the label turned to run along it (it then needs only its height of room, not its width) — then
  // the same on the opposite side; then each one gap further out. The label sits on its dimension line (middle first, then slid along it).
  // The first fully clean candidate wins; else the one with the fewest violations — still beside
  // its own shape, never floating.
  const s = scale();
  const box = minAreaBox(points);
  const [halfW, halfH] = labelBox(text, 0, 0).slice(2);
  const across = box[along === "u" ? "v" : "u"];
  const steep = Math.abs(across[0]) > Math.abs(across[1]);
  // The line keeps half the label's size across it, plus a margin, away from the shape.
  const gapFor = (turned) => Math.max(30 * s,
    (turned ? halfH : Math.abs(across[0]) * halfW + Math.abs(across[1]) * halfH) + 10 * s);
  const away = preferredSide(box, along, avoidPolys);
  const modes = steep ? [false, true] : [false];
  const candidates = [];
  for (const k of [1, 1.8]) for (const side of [away, -away]) for (const turned of modes) {
    const g = extentGeometry(points, box, along, side, gapFor(turned) * k);
    let [dx, dy] = [g.b[0] - g.a[0], g.b[1] - g.a[1]];
    if (dy > 0) [dx, dy] = [-dx, -dy];  // a turned label reads bottom to top
    const angle = turned ? Math.atan2(dy, dx) : 0;
    for (const t of [0.5, 0.35, 0.65, 0.2, 0.8]) {
      candidates.push({ ...g, angle, middle: [g.a[0] + (g.b[0] - g.a[0]) * t, g.a[1] + (g.b[1] - g.a[1]) * t] });
    }
  }
  const polys = [ownPoly, ...avoidPolys];
  const clear = (p, q) => lineFits(p, q) && !polys.some((poly) => segHitsPoly(p, q, poly))
    && !placedLines.some(([r, t]) => segsCross(p, q, r, t));
  const violations = (c) => (labelFits(labelBox(text, ...c.middle, undefined, c.angle), polys,
    c.angle ? labelCorners(text, c.middle, c.angle) : null) ? 0 : 1)
    + (clear(c.a, c.b) ? 0 : 1) + c.ext.filter(([p, q]) => !clear(p, q)).length;
  const scored = candidates.map((c) => ({ ...c, violations: violations(c) }));
  const best = scored.find((c) => c.violations === 0)
    || scored.reduce((x, y) => (y.violations < x.violations ? y : x));
  const middle = best.violations === 0 ? best.middle : clampInside(text, best.middle);
  context.strokeStyle = css("--color-dimension");
  context.lineWidth = 1.5 * s;
  context.beginPath();
  for (const [p, q] of best.ext) { context.moveTo(...p); context.lineTo(...q); }
  context.stroke();
  dimensionLine(best.a[0], best.a[1], best.b[0], best.b[1]);
  placedLines.push([best.a, best.b], ...best.ext);
  dimensionLines.push([best.a, best.b]);
  callout(text, middle[0], middle[1], undefined, best.angle);
  occupied.push(labelBox(text, ...middle, undefined, best.angle));
}

function drawCard(corners, ownPoly, avoidPolys) {
  // The card's known size (ID-1, 85.60 × 53.98 mm) along its long and short side, just outside.
  extentDimension(corners, "u", "85.60 mm", ownPoly, avoidPolys);
  extentDimension(corners, "v", "53.98 mm", ownPoly, avoidPolys);
}

function drawMeasurements(a, fx) {
  fx = fx || { outline: 1, dims: 1 };  // measure intro: the contour draws itself, then the dimensions fade in
  const s = scale();
  occupied = [];
  placedLines = [];
  dimensionLines = [];
  polygon(a.card_corners_px, css("--color-overlay-card"), 2);
  polygon(a.outline_px, css("--color-overlay-part"), Number(css("--overlay-line-width")), true, true, fx.outline);
  a.holes.forEach((hole) => polygon(hole.contour_px, css("--color-overlay-hole"), 2));

  const cardPoly = a.card_corners_px;
  const partPoly = a.outline_px;
  const holePolys = a.holes.map((hole) => hole.contour_px);
  if (state.click) {  // the tap marker drawn on top: its reticle and its "SELECTED PART" tag
    occupied.push([state.click[0] - 30 * s, state.click[1] - 30 * s, state.click[0] + 30 * s, state.click[1] + 30 * s]);
    occupied.push([state.click[0] - 70 * s, state.click[1] + 34 * s, state.click[0] + 70 * s, state.click[1] + 64 * s]);
  }

  // The part's extents first (their labels matter most), along its own axes; then the holes; then the card.
  context.save();
  context.globalAlpha = fx.dims;
  extentDimension(partPoly, "u", mm(a.outline_mm.length), partPoly, [cardPoly]);
  extentDimension(partPoly, "v", mm(a.outline_mm.width), partPoly, [cardPoly]);
  const pxPerMm = 1 / a.card_mm_per_pixel;
  for (const group of holeGroups(a.holes)) {
    const placed = group.holes.length > 1
      && placeHoleLabel(group.holes, a.holes, holeGroupText(group), holePolys, cardPoly, partPoly,
        LEADER_LIMIT_MM * pxPerMm);
    if (!placed) for (const hole of group.holes) {
      placeHoleLabel([hole], a.holes, holeGroupText({ ...group, holes: [hole] }), holePolys, cardPoly, partPoly, null);
    }
  }
  drawCard(a.card_corners_px, cardPoly, [partPoly]);
  context.restore();
}

function holeGroups(holes) {
  // Holes of the same shape and nearly the same size (within 0.25 mm or 4%) share one label.
  const groups = [];
  for (const hole of holes) {
    const size = holeSize(hole);
    const group = groups.find((g) => g.shape === hole.shape && Math.abs(g.size - size) <= Math.max(0.25, 0.04 * size));
    if (group) group.holes.push(hole);
    else groups.push({ shape: hole.shape, size, holes: [hole] });
  }
  return groups;
}

const holeSize = (hole) => Number(hole.size.match(/[\d.]+/)[0]);  // diameter, or length for other shapes

function holeGroupText(group) {
  const count = group.holes.length > 1 ? `${group.holes.length}× ` : "";
  if (group.shape === "circle") {
    const mean = group.holes.reduce((sum, h) => sum + holeSize(h), 0) / group.holes.length;
    return `${count}Ø${mean.toFixed(1)}`;
  }
  return `${count}${group.holes[0].size.replace(" mm", "")}`;
}

const LEADER_LIMIT_MM = 12;  // equal holes share one label only while every leader (center to
  // center) stays this short: about 5 mm of visible leader. Tighter admits nothing — the label alone
  // needs ~11 mm of span to clear two adjacent holes — while spread holes still split (their shared
  // label would have to cover a hole to keep every leader short).

function ringSpots([cx, cy], base, radii) {
  // Candidate label centers on rings around a point, nearest first; the 8 compass points first
  // (labels aligned with the part read best), then the 8 half-offset angles, so a valid spot
  // between grid points — e.g. a shared label just inside a tilted edge — is still found.
  const s = scale();
  const steps = [0, 1, 2, 3, 4, 5, 6, 7, 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5];
  return radii.flatMap((extra) => steps.map((k) => {
    const angle = (k / 8) * 2 * Math.PI;
    return [cx + Math.cos(angle) * (base + extra * s), cy + Math.sin(angle) * (base + extra * s)];
  }));
}

function holeRadiusPx(hole) {
  const xs = hole.contour_px.map(([x]) => x), ys = hole.contour_px.map(([, y]) => y);
  return Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) / 2;
}

function leaderBlocked(from, to, self, holePolys, cardPoly, partPoly, outside = false) {
  // A leader may not cross a label, the card, the part's edge, or another hole (its own hole is where
  // it ends). From a label outside the part (`outside`), it crosses the part's edge once to reach in.
  const pad = 4 * scale();
  if ([...occupied].some((o) => segHitsBox(from, to, [o[0] - pad, o[1] - pad, o[2] + pad, o[3] + pad]))) return true;
  if (segHitsPoly(from, to, cardPoly)) return true;
  if (!outside && segCrossesPoly(from, to, partPoly)) return true;
  if (dimensionLines.some(([a, b]) => segsCross(from, to, a, b))) return true;  // nor a dimension line
  return holePolys.some((poly, j) => j !== self && segHitsPoly(from, to, poly));
}

function placeHoleLabel(holes, allHoles, text, holePolys, cardPoly, partPoly, limitPx) {
  // One label next to these holes with a short leader to each; a group that cannot keep every
  // leader short reports back, so the caller labels each hole instead. Singles always draw.
  const s = scale();
  const centers = holes.map((h) => h.center_px);
  const ids = holes.map((h) => allHoles.indexOf(h));
  const middle = [centers.reduce((t, c) => t + c[0], 0) / centers.length,
                  centers.reduce((t, c) => t + c[1], 0) / centers.length];
  const base = holes.length > 1 ? 0 : holeRadiusPx(holes[0]);
  const avoid = [cardPoly, ...holePolys];
  // Inside the part first (the label clear of its edge, the leader staying inside); a single hole
  // whose part has no room left gets its label just outside the part instead.
  // Spots are tried nearest first; an outside spot counts one ring step farther than it is.
  const tries = ringSpots(middle, base, holes.length > 1 ? [30, 60, 100, 160] : [30, 60, 100])
    .map((spot, order) => ({ spot, outside: false, cost: Math.hypot(spot[0] - middle[0], spot[1] - middle[1]), order }));
  if (holes.length === 1) {
    tries.push(...ringSpots(middle, base, [30, 60, 100, 140, 180, 240]).map((spot, order) => ({ spot, outside: true,
      cost: Math.hypot(spot[0] - middle[0], spot[1] - middle[1]) + 40 * s, order: order + 1000 })));
  }
  tries.sort((p, q) => p.cost - q.cost || p.order - q.order);
  for (const { spot: [x, y], outside } of tries) {
    const box = labelBox(text, x, y, 16);
    if (!labelFits(box, outside ? [...avoid, partPoly] : avoid)) continue;
    const padded = [box[0] - 3 * s, box[1] - 3 * s, box[2] + 3 * s, box[3] + 3 * s];
    if (partPoly.some((c, i) => segHitsBox(c, partPoly[(i + 1) % partPoly.length], padded))) continue;  // off the part's edge
    const leaders = centers.map((c) => [[x, y], c]);
    if (limitPx != null && leaders.some(([[x0, y0], [x1, y1]]) => Math.hypot(x1 - x0, y1 - y0) > limitPx)) continue;
    if (leaders.some(([p, c], i) => leaderBlocked(p, c, ids[i], holePolys, cardPoly, partPoly, outside))) continue;
    context.strokeStyle = css("--color-overlay-hole");
    context.lineWidth = 1.5 * s;
    context.beginPath();
    for (const [hx, hy] of centers) { context.moveTo(x, y); context.lineTo(hx, hy); }
    context.stroke();
    callout(text, x, y, 16);
    occupied.push(labelBox(text, x, y, 16));
    return true;
  }
  if (holes.length > 1) return false;
  const [x, y] = clampInside(text, middle, 16);  // no free spot: on the hole, like before
  callout(text, x, y, 16);
  occupied.push(labelBox(text, x, y, 16));
  return true;
}

function clampInside(text, [x, y], fontPx) {
  // Move a label's center so its whole box stays inside the photo.
  const [left, top, right, bottom] = labelBox(text, x, y, fontPx);
  const pad = 4 * scale();
  return [x + Math.max(pad - left, 0) - Math.max(right - (canvas.width - pad), 0),
          y + Math.max(pad - top, 0) - Math.max(bottom - (canvas.height - pad), 0)];
}

function drawClick() {
  // The tap marker: a reticle at the click, labelled once the part has been found there.
  if (!state.click) return;
  const [x, y] = state.click;
  const s = scale();
  const orange = css("--color-overlay-click");
  context.save();
  context.strokeStyle = orange;
  context.fillStyle = orange;
  context.lineWidth = 3 * s;
  context.beginPath();
  context.arc(x, y, 16 * s, 0, 2 * Math.PI);
  context.stroke();
  context.beginPath();
  context.arc(x, y, 5 * s, 0, 2 * Math.PI);
  context.fill();
  context.beginPath();
  for (const [dx, dy] of [[0, -1], [0, 1], [-1, 0], [1, 0]]) {
    context.moveTo(x + dx * 20 * s, y + dy * 20 * s);
    context.lineTo(x + dx * 28 * s, y + dy * 28 * s);
  }
  context.stroke();
  if (state.analysis) {
    context.font = `700 ${14 * s}px ${css("--font-mono")}`;
    const text = "SELECTED PART";
    const width = context.measureText(text).width + 16 * s;
    context.fillRect(x - width / 2, y + 36 * s, width, 24 * s);
    context.fillStyle = css("--color-text-on-accent");
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, x, y + 48 * s);
  }
  context.restore();
}

function render() {
  if (!state.image) return;
  canvas.width = state.image.naturalWidth;
  canvas.height = state.image.naturalHeight;
  context.drawImage(state.image, 0, 0);
  if (state.analysis) drawMeasurements(state.analysis, state.fx);
  drawClick();
  updateBadges();
}
window.addEventListener("resize", render);

function updateBadges() {
  const a = state.analysis;
  $("scale-badge").classList.toggle("hidden", !a);
  $("found-badge").classList.toggle("hidden", !a);
  if (!a) return;
  const barPx = 10 / a.card_mm_per_pixel / scale();  // 10 mm on screen
  const [w, h] = a.image_size.map((v) => (v * a.card_mm_per_pixel).toFixed(1));
  $("scale-badge").innerHTML = `<span class="scale-bar" style="width:${barPx.toFixed(0)}px"></span><span>10 mm</span>`
    + `<span class="sep">|</span><span class="muted">Photo at the card: <span>${w} × ${h} mm</span></span>`;
  $("found-badge").innerHTML = `<span class="pulse"></span>Part outline: SAM 3.1 · ${a.part_found_by}`;
}

function thickness() {
  const value = Number(String($("thickness").value).replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function updateProcedure() {
  const a = state.analysis;
  const steps = { card: !!a, photo: !!a, click: !!(a && state.click) };
  for (const key of Object.keys(steps)) {  // an empty circle until done; the tap step keeps its hint icon
    $(`step-${key}`).classList.toggle("done", steps[key]);
    $(`step-${key}`).querySelector(".step-icon .icon").textContent
      = steps[key] ? "check" : key === "click" ? "touch_app" : "radio_button_unchecked";
  }
  $("step-click").classList.toggle("current", !!state.image && !steps.click);
  $("step-card-sub").textContent = a ? `Card found · ${a.card_mm_per_pixel} mm/px` : "Card found when measured";
  $("step-photo-sub").textContent = a
    ? `Card edges differ ${a.card_edge_differences_pct.map((d) => Math.abs(d).toFixed(1)).join(" / ")} %`
    : "Checked from the card's edges";
  $("step-click-sub").textContent = a
    ? `Part found · ${a.outline_mm.corners} corners · ${a.holes.length} holes`
    : state.click ? "Clicked: press Measure" : "Click the part, not a hole";
  const t = thickness();
  document.querySelectorAll("#thickness-presets button").forEach((b) => b.classList.toggle("active", Number(b.dataset.thickness) === t));
  if (a) showSummary(a);
}

function showSummary(a) {
  const t = thickness();
  const sizes = a.holes.map((h) => h.size.replace(" mm", "")).join("  ");
  const rows = [["Part extents", `${a.outline_mm.length.toFixed(2)} × ${a.outline_mm.width.toFixed(2)} × ${t ? t.toFixed(2) : "?"} mm`],
                ["Corners", a.outline_mm.corners], [`Holes (${a.holes.length})`, sizes || "none"],
                ["Scale", `1 px = ${a.card_mm_per_pixel} mm`]];
  $("measure-table").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td class="number">${v}</td></tr>`).join("");
  const warning = a.resolution_warning;
  $("resolution-warning").classList.toggle("hidden", !warning);
  if (warning) $("resolution-warning-text").textContent = warning;
  const tilt = a.tilt_warning;
  $("tilt-warning").classList.toggle("hidden", !tilt);
  if (tilt) $("tilt-warning-text").textContent = tilt;
  $("measure-results").classList.remove("hidden");
}

function updateCaptureBars() {
  const a = state.analysis;
  $("photo-size").textContent = state.image ? `${state.image.naturalWidth} × ${state.image.naturalHeight} px` : "";
  $("capture-subbar-right").innerHTML = a
    ? `<span>SCALE <strong>1 px = ${a.card_mm_per_pixel} mm</strong> (${a.scale_used})</span>`
      + `<span>MASKS <strong>SAM 3.1</strong></span>` : "";
  $("capture-footer-values").innerHTML = a
    ? `<span>Card edges <strong>${a.card_edge_differences_pct.join(" / ")} %</strong></span>`
      + `<span>Keypoints <strong>${a.outline_mm.corners} corners / ${a.holes.length} holes</strong></span>`
      + `<span>Holes by <strong>${a.hole_method}</strong></span>` : "";
}

function resetResults() {
  state.analysis = null;
  state.splitWarning = null;
  updateSplitButtons();
  state.done = null;
  state.winner = null;
  $("measure-results").classList.add("hidden");
  $("resolution-warning").classList.add("hidden");
  $("tilt-warning").classList.add("hidden");
  $("to-candidates").classList.add("hidden");
  $("analyze").classList.remove("hidden");
  $("capture-status").textContent = "";
  enableSteps();
  updateProcedure();
  updateCaptureBars();
}

function setLive(live) {
  state.live = live;
  document.querySelectorAll(".live-only").forEach((element) => element.classList.toggle("hidden", !live));
}

function showPhoto() {
  $("stage-empty").classList.add("hidden");
  canvas.classList.remove("hidden");
  setScreen("capture");
  updateProcedure();
  updateCaptureBars();
}

async function chooseRun(name) {
  setLive(false);
  state.run = name;
  resetResults();
  watch.reset();
  document.querySelectorAll("#example-list button, #your-runs-list button")
    .forEach((b) => b.classList.toggle("active", b.dataset.run === name));
  state.image = await loadImage(`/api/runs/${name}/photo`);
  const about = await getJSON(`/api/runs/${name}/info`);
  state.click = about.click_px;  // the example's own click
  state.runKind = about.kind;  // "Synthetic" or "Real photo", the same source as the gallery badge
  state.sample = about.sample;
  updateHeader();
  showPhoto();
  $("analyze").disabled = false;
}

$("photo-upload").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("photo", file);
  const response = await fetch("/api/live/upload", { method: "POST", body: form });
  if (!response.ok) {
    $("capture-status").textContent = `Upload failed: ${(await response.json()).detail}`;
    return;
  }
  const { name } = await response.json();
  setLive(true);
  state.run = name;
  resetResults();
  watch.reset();
  document.querySelectorAll("#example-list button, #your-runs-list button").forEach((b) => b.classList.remove("active"));
  state.click = null;  // live: the user clicks the part
  state.image = await loadImage(`/api/runs/${name}/photo`);
  showPhoto();
  $("analyze").disabled = true;
  $("capture-status").textContent = "Click the part in the photo (not a hole).";
});

canvas.addEventListener("click", (event) => {
  if (!state.image) return;
  const box = canvas.getBoundingClientRect();
  state.click = [Math.round((event.clientX - box.left) * (canvas.width / box.width)),
                 Math.round((event.clientY - box.top) * (canvas.height / box.height))];
  if (state.analysis) { resetResults(); watch.reset(); }  // a new click means a new measurement
  render();
  updateProcedure();
  $("analyze").disabled = false;
});

function setThickness(value) {
  $("thickness").value = Math.max(0.5, value).toFixed(1);
  updateProcedure();
}
$("thickness-down").addEventListener("click", () => setThickness((thickness() ?? 3) - 0.5));
$("thickness-up").addEventListener("click", () => setThickness((thickness() ?? 3) + 0.5));
$("thickness").addEventListener("input", updateProcedure);
document.querySelectorAll("#thickness-presets button").forEach((b) =>
  b.addEventListener("click", () => setThickness(Number(b.dataset.thickness))));

function showScan() {
  if (reducedMotion()) return;
  $("scanline").classList.remove("hidden");
}
function hideScan() { $("scanline").classList.add("hidden"); }

function playMeasureIntro() {
  // The mask contour draws itself as an orange line, then the dimension lines fade in with
  // their final numbers. Purely visual: nothing waits for it.
  if (reducedMotion() || state.screen !== "capture") { state.fx = null; render(); hideScan(); return; }
  if (!state.live) { showScan(); setTimeout(hideScan, 900); }  // replay has no live SAM stage to watch
  else hideScan();  // live: the scan ran while SAM worked; the mask has arrived
  const t0 = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - t0) / 900);
    state.fx = { outline: 1 - Math.pow(1 - t, 3), dims: Math.max(0, Math.min(1, (t - 0.35) / 0.65)) };
    if (t >= 1 || state.screen !== "capture") { state.fx = null; render(); return; }
    render();
    requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function showAnalysis(a) {
  state.analysis = a;
  $("analyze").classList.add("hidden");
  $("to-candidates").classList.remove("hidden");
  playMeasureIntro();
  updateProcedure();
  updateCaptureBars();
  enableSteps();
}

function measureLive() {
  return new Promise((resolve) => {
    const status = $("capture-status");
    const [x, y] = state.click;
    showScan();
    const stream = new EventSource(`/api/live/${state.run}/measure/stream?x=${x}&y=${y}`);
    stream.addEventListener("progress", (m) => (status.textContent = JSON.parse(m.data).message));
    stream.addEventListener("analysis", (m) => {
      stream.close();
      status.textContent = "";
      showAnalysis(JSON.parse(m.data));
      watch.pause();
      resolve();
    });
    stream.addEventListener("error", (m) => {
      stream.close();
      status.textContent = m.data ? `Failed: ${JSON.parse(m.data).message}` : "The connection was lost.";
      hideScan();
      watch.pause();
      resolve();
    });
  });
}

async function measure() {
  $("analyze").disabled = true;
  $("analyze-label").textContent = "Measuring…";
  if (state.live) { watch.start(); await measureLive(); }
  else showAnalysis(await getJSON(`/api/runs/${state.run}/analysis`));
  $("analyze-label").textContent = "Measure";
  $("analyze").disabled = false;
}
$("analyze").addEventListener("click", measure);

// ---------- search ----------
const escapeAttribute = (text) => String(text).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const percent = (model, truth) => `${model - truth >= 0 ? "+" : "−"}${Math.abs((100 * (model - truth)) / truth).toFixed(1)}%`;

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function scoreLine(event) {
  // IoU, and the fit to the measurements when it was checked (title explains the number).
  if (event.iou == null) return `<span>no shape</span>`;
  const fit = event.fit_mm == null ? ""
    : `<span title="fit to measurements: largest distance from a measured outline point to this candidate's outline">fit ${event.fit_mm.toFixed(2)}mm</span>`;
  return `<span>IoU ${event.iou.toFixed(3)}</span>${fit}`;
}

function resultRows(event) {
  // [label, value] rows for what was computed for this candidate; rows without a value are left out.
  const rows = [];
  if (event.fit_mm != null) rows.push(["Fit to measurements", mm(event.fit_mm)]);
  const truth = event.ground_truth;
  if (truth) {
    const ruler = truth.kind === "ruler";
    rows.push([ruler ? "vs ruler (±0.5 mm)" : "vs ground truth", null]);  // a heading row
    for (const key of ["length", "width"]) {
      const [model, real] = truth[key];
      rows.push([key === "length" ? "Length" : "Width", `${model.toFixed(2)} vs ${real.toFixed(2)} (${percent(model, real)})`]);
    }
    if (truth.holes && truth.holes.length) {
      if (ruler) {  // a ruler reads ±0.5 mm: measured vs ruler per hole, no tighter claim
        truth.holes.forEach(([model, real], i) => rows.push([`Hole ${i + 1}`, `Ø${model.toFixed(2)} vs ${real}`]));
      } else {
        const worst = Math.max(...truth.holes.map(([model, real]) => Math.abs(model - real)));
        rows.push(["Holes", `Ø within ${mm(worst)}`]);
      }
    }
  }
  if (event.parameters != null) rows.push(["Parameters", event.parameters]);
  return rows;
}

const MODEL_NAMES = { "sam-3.1": "SAM 3.1", "meta-models/muse-spark-open-1026": "Muse Spark Open", "muse-wonder-1.0": "Muse Wonder", "muse-voice-transcribe-1.0": "Muse Voice Transcribe" };
const sourceLabel = (source) => (source === "candidate" ? "candidate · Muse Spark Open" : source);

function usageRows(usage) {
  // One row per model this run called (from the run's usage ledger), then the total of the known prices.
  const rows = Object.entries(usage.models).map(([model, t]) => {
    const amount = t.images ? `${t.images} images` : `${(t.input_tokens + t.output_tokens).toLocaleString("en-US")} tokens`;
    const price = t.cost_usd == null ? "price unknown" : `$${t.cost_usd.toFixed(3)}${t.price_unverified ? " (unverified)" : ""}`;
    return [MODEL_NAMES[model] || model, `${t.calls} calls · ${amount} · ${price}`];
  });
  rows.push(["Known cost", `$${usage.known_cost_usd.toFixed(3)}`]);
  return rows;
}

const tableHTML = (rows) => rows.map(([k, v]) => (v === null
  ? `<tr class="heading"><td colspan="2">${k}</td></tr>` : `<tr><td>${k}</td><td class="number">${v}</td></tr>`)).join("");

function candidateCard(event) {
  const card = document.createElement("div");
  card.className = `candidate-card ${event.status}`;
  card.id = `candidate-${event.candidate}`;
  const reference = `<img class="shape-ref" src="/api/runs/${state.run}/reference.png" alt="" onerror="this.remove()">`;
  const picture = event.silhouette ? reference + `<img class="shape-cand" src="${event.silhouette}" alt="candidate ${event.candidate} silhouette">` : "";
  const reason = event.reasons.length  // plain words on the card, the technical text on hover
    ? `<div class="reason" title="${escapeAttribute(event.reasons.join("\n"))}">${event.plain_reasons[0]}</div>` : "";
  const status = { passed: "PASS", rejected: "REJECTED", failed: "FAILED" }[event.status];
  card.innerHTML = `<header><span>#${idOf(event)}</span><span class="status-chip">${status}</span></header>`
    + `<div class="shape">${picture}${reason}</div><div class="scores">${scoreLine(event)}</div>`;
  if (event.status === "rejected" || event.status === "failed") {  // visible fade-out, then the reason stays
    if (reducedMotion()) card.classList.add("settled");
    else requestAnimationFrame(() => requestAnimationFrame(() => card.classList.add("settled")));
  }
  return card;
}

function winnerCard(event) {
  const card = document.createElement("div");
  card.className = "candidate-card winner";
  card.id = `candidate-${event.candidate}`;
  const length = event.outline_mm ? `<div class="dimension"><span class="line" style="left:12%;right:12%"></span>`
    + `<span>${mm(event.outline_mm[0])}</span></div>` : "";
  const fit = event.fit_mm == null ? ""
    : `<div><span class="label">Fit to measurements</span><span class="big-plain">${mm(event.fit_mm)}</span></div>`;
  const truth = event.ground_truth
    ? `<div class="truth-line">${event.ground_truth.kind === "ruler" ? "vs ruler (±0.5 mm)" : "vs ground truth"}: ${event.ground_truth.length[0].toFixed(2)} × ${event.ground_truth.width[0].toFixed(2)}`
      + ` vs ${event.ground_truth.length[1].toFixed(2)} × ${event.ground_truth.width[1].toFixed(2)} mm`
      + ` (${percent(...event.ground_truth.length)} / ${percent(...event.ground_truth.width)})</div>` : "";
  const diagnosis = event.label && event.diagnosis  // a repaired program says what was wrong with the rest
    ? `<div class="repair-diagnosis"><span class="label">Repaired by Muse Wonder</span>${escapeAttribute(event.diagnosis)}</div>` : "";
  card.innerHTML = `<div class="winner-head"><span class="winner-id"><span class="winner-number">#${idOf(event)}</span>${event.label ? "REPAIRED" : "BEST MATCH"}</span>`
    + `<span class="winner-chip">Selected · ${event.parameters} params</span></div>`
    + `<div class="shape">${length}<img class="shape-ref" src="/api/runs/${state.run}/reference.png" alt="" onerror="this.remove()">`
    + `<img class="shape-cand" src="${event.silhouette}" alt="selected candidate silhouette"></div>`
    + `${diagnosis}<div class="winner-scores"><div><span class="label">Overlap (IoU)</span><span class="big-accent">IoU ${event.iou.toFixed(4)}</span></div>`
    + `${fit}</div>${truth}`;
  return card;
}

function layoutGrid() {
  // Cards for candidates still on their way (live), then columns and rows chosen so the cards are as
  // large as the space allows for this many candidates (the selected one takes 2 × 2).
  const grid = $("candidate-grid");
  grid.querySelectorAll(".waiting").forEach((e) => e.remove());
  const arrived = state.seen.length;
  const waiting = state.done ? 0 : Math.max((state.expected || 0) - arrived, 0);
  for (let i = 0; i < waiting; i++) {
    const card = document.createElement("div");
    card.className = "candidate-card waiting";
    card.innerHTML = `<header><span>#${pad2(arrived + i + 1)}</span><span class="status-chip">queued</span></header>`
      + `<div class="shape">waiting</div><div class="scores"><span>–</span></div>`;
    grid.appendChild(card);
  }
  const cells = Math.max(arrived + waiting + (grid.querySelector(".winner") ? 3 : 0), 1);
  const [width, height] = [grid.clientWidth || 1000, grid.clientHeight || 700];
  let best = null;
  for (let columns = 2; columns <= 8; columns++) {
    // The measured-shape panel (no candidate passed) spans the full width and two rows.
    const rows = Math.ceil((cells + (grid.querySelector(".fallback-card") ? 2 * columns - 1 : 0)) / columns);
    const size = Math.min(width / columns / 1.15, height / rows);  // the card height its cell allows
    if (!best || size > best.size) best = { columns, rows, size };
  }
  grid.style.gridTemplateColumns = `repeat(${best.columns}, minmax(0, 1fr))`;
  grid.style.gridTemplateRows = `repeat(${best.rows}, minmax(0, 1fr))`;
}

function streamItem(tag, tagClass, text, detail = "") {
  // Live: the wall clock. Replay: the time since the replay started (a replay is not a call made now).
  const now = new Date();
  const time = state.live || state.streamStarted == null
    ? `${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}.${String(now.getMilliseconds()).padStart(3, "0")}`
    : `replay +${((performance.now() - state.streamStarted) / 1000).toFixed(1)} s`;
  const item = document.createElement("div");
  item.className = "stream-item";
  if (detail) item.title = detail;
  item.innerHTML = `<div class="when"><span>${time}</span><span class="${tagClass}">${tag}</span></div><span class="text">${text}</span>`;
  $("stream").prepend(item);
}

function updateSummary() {
  const seen = state.seen;
  const passed = seen.filter((e) => e.status === "passed");
  $("search-count").textContent = seen.length;
  $("search-total").textContent = `${state.done ? state.done.candidate_count : state.expected || seen.length} requested`;
  $("search-split").innerHTML = `<strong>${passed.length} passed</strong> · ${seen.length - passed.length} rejected or failed`;
  // The selected candidate once the round is done; until then the passed one with the highest IoU.
  const chosen = state.done ? seen.find((e) => e.candidate === state.done.winner)
    : passed.reduce((x, y) => (x && x.iou >= y.iou ? x : y), null);
  $("pick-label").textContent = state.done ? "Selected" : "Leading so far";
  $("pick-name").textContent = chosen ? `#${idOf(chosen)}` : state.done ? state.done.note || state.done.result_source || "no result" : "–";
  $("pick-iou").textContent = chosen ? `IoU ${chosen.iou.toFixed(4)}` : "";
  $("pick-table").innerHTML = chosen ? tableHTML(resultRows(chosen)) : "";
  const usage = state.done && state.done.usage;
  $("usage-box").classList.toggle("hidden", !(usage && Object.keys(usage.models).length));
  if (usage) $("usage-table").innerHTML = tableHTML(usageRows(usage));
  const a = state.analysis;
  $("search-target").innerHTML = a ? `Target <strong>${a.outline_mm.length.toFixed(2)} × ${a.outline_mm.width.toFixed(2)} mm · ${a.holes.length} holes</strong>` : "";
  $("search-state").innerHTML = state.done ? "" : `<span class="pulse"></span>Checking ${seen.length + 1}${state.expected ? ` / ${state.expected}` : ""}`;
  $("stream-dot").classList.toggle("idle", !!state.done);
  updateHeader();
}

const wonderCard = {
  // A status card in the main area while a Muse Wonder request runs (repair or completion): live it
  // counts the elapsed seconds, replay shows the recorded duration briefly. Hidden when the answer arrives.
  timer: null,
  show(kind, recordedSeconds, parent, before = null, extraClass = "") {
    this.hide();
    const titles = { repair: "Muse Wonder is repairing the candidates…", completion: "Asking Muse Wonder for a completion…" };
    const card = document.createElement("div");
    card.className = `wonder-card ${extraClass}`;
    card.id = "wonder-card";
    const sub = document.createElement("span");
    sub.className = "wonder-sub";
    card.innerHTML = `<span class="icon accent">psychology</span><span class="wonder-title">${titles[kind]}</span>`;
    card.appendChild(sub);
    parent.insertBefore(card, before);
    if (recordedSeconds == null) {
      const started = Date.now();
      const tick = () => (sub.textContent = `${Math.floor((Date.now() - started) / 1000)} s elapsed · usually 1–2 min`);
      tick();
      this.timer = setInterval(tick, 1000);
    } else {
      sub.textContent = `Recorded run · took ${recordedSeconds} s`;
    }
  },
  hide() {
    clearInterval(this.timer);
    this.timer = null;
    document.querySelectorAll("#wonder-card").forEach((e) => e.remove());
  },
};

function wonderShow(kind, seconds) {
  // The wait, at the top of the search screen's main area.
  const main = document.querySelector(".search-main");
  wonderCard.show(kind, seconds, main, main.firstChild);
}

function streamCandidates() {
  return new Promise((resolve) => {
    if (state.stream) state.stream.close();
    wonderCard.hide();
    state.done = null;
    state.winner = null;
    state.seen = [];
    state.expected = state.live ? Number($("candidate-count").value) : null;
    state.streamStarted = performance.now();  // replayed stream rows count from here
    setScreen("search");
    const grid = $("candidate-grid");
    grid.innerHTML = "";
    $("stream").innerHTML = "";
    $("search-round").textContent = "";
    showNoDesign(false);
    enableSteps();
    $("to-model").disabled = true;
    layoutGrid();
    updateSummary();
    const count = $("candidate-count").value;
    if (state.live) watch.resume();
    state.stream = new EventSource(state.live
      ? `/api/live/${state.run}/candidates/stream?count=${count}&thickness=${thickness() ?? 3}`
      : `/api/runs/${state.run}/candidates/stream${state.round ? `?round=${state.round}` : ""}`);
    state.stream.addEventListener("progress", (m) => streamItem("…", "tag-ok", JSON.parse(m.data).message));
    state.stream.addEventListener("repair_started", (m) => wonderShow("repair", JSON.parse(m.data).seconds));
    state.stream.addEventListener("completion_started", () => wonderShow("completion", null));
    state.stream.addEventListener("repair", (m) => {
      // A Muse Wonder repair round: its diagnosis, and whether its program passed the same checks.
      wonderCard.hide();
      const r = JSON.parse(m.data);
      streamItem(r.passed ? "REPAIRED" : "REPAIR", r.passed ? "tag-best" : "tag-bad",
        `repair round ${r.round} · Muse Wonder: ${r.passed ? `passed, IoU ${r.iou.toFixed(4)}` : "not passed"}. ${r.diagnosis || ""}`,
        r.reasons.join("\n"));
    });
    state.stream.addEventListener("candidate", (m) => {
      wonderCard.hide();
      const event = JSON.parse(m.data);
      state.seen.push(event);
      grid.insertBefore(candidateCard(event), grid.querySelector(".waiting"));
      if (event.status === "passed") {
        const fit = event.fit_mm == null ? "" : `, fit ${event.fit_mm.toFixed(2)} mm`;
        streamItem("OK", "tag-ok", `candidate ${idOf(event)}${event.style ? ` (${event.style.replace(/_/g, " ")})` : ""} passed: IoU ${event.iou.toFixed(4)}${fit}`);
      } else {
        streamItem(event.status === "failed" ? "FAIL" : "REJECT", "tag-bad",
          `candidate ${idOf(event)} ${event.status}: ${event.plain_reasons[0] || "no reason given"}`, event.reasons.join("\n"));
      }
      layoutGrid();
      updateSummary();
    });
    state.stream.addEventListener("done", (m) => {
      state.stream.close();
      wonderCard.hide();
      state.done = JSON.parse(m.data);
      watch.finish(state.done.durations);
      $("search-round").innerHTML = `Round <strong>${state.done.round}</strong>`;
      const chosen = state.seen.find((e) => e.candidate === state.done.winner);
      if (chosen) {
        $(`candidate-${chosen.candidate}`).replaceWith(winnerCard(chosen));
        streamItem("BEST", "tag-best", chosen.label ? `repaired program ${chosen.label} selected (Muse Wonder)` : `candidate ${idOf(chosen)} selected: correct shape, best IoU, fewest parameters`);
      } else {
        streamItem("FALLBACK", "tag-bad", state.done.note || `no candidate passed: ${state.done.result_source}`);
        if (state.done.fallback) grid.prepend(fallbackCard(state.done.fallback));
        showNoDesign(true);
      }
      $("to-model").disabled = !state.done.result_source || state.done.result_source.startsWith("none");
      layoutGrid();
      updateSummary();
      enableSteps();
      resolve();
    });
    state.stream.addEventListener("error", (m) => {
      state.stream.close();
      wonderCard.hide();
      streamItem("ERROR", "tag-bad", m.data ? JSON.parse(m.data).message : "The candidate stream stopped unexpectedly.");
      watch.pause();
      resolve();
    });
  });
}
$("to-candidates").addEventListener("click", streamCandidates);

function fallbackCard(fallback) {
  // No candidate passed: the measured shape (the baseline built straight from the measurements), full width.
  const card = document.createElement("div");
  card.className = "candidate-card fallback-card";
  const length = fallback.outline_mm ? `<div class="dimension"><span class="line" style="left:14%;right:14%"></span>`
    + `<span>${mm(fallback.outline_mm[0])}</span></div>` : "";
  const fit = fallback.fit_mm == null ? "" : `<span>Fit <strong>${mm(fallback.fit_mm)}</strong></span>`;
  card.innerHTML = `<div class="fallback-head"><span class="fallback-title">Measured shape</span>`
    + `<span class="fallback-chip">Fallback</span><span class="fallback-scores"><span>IoU <strong>${fallback.iou.toFixed(4)}</strong></span>${fit}</span></div>`
    + `<div class="shape">${length}<img src="${fallback.silhouette}" alt="the measured shape"></div>`
    + `<span class="fallback-foot">Built straight from the measurements: every corner and hole is its own parameter (${fallback.parameters}); no design intent.</span>`;
  return card;
}

async function showNoDesign(show) {
  // The side panel when no candidate passed: why, what to do, and what the break cues measured.
  $("nodesign").classList.toggle("hidden", !show);
  $("irregular").classList.toggle("hidden", !show);
  $("pick-box").classList.toggle("hidden", show);
  $("to-model").classList.toggle("hidden", show);
  if (!show) return;
  const note = state.done.note || "No candidate passed every check; the measured shape is shown.";
  $("nodesign-title").textContent = note.split(";")[0].replace(/^The /, "").replace(/^./, (c) => c.toUpperCase());
  const r = await getJSON(`/api/runs/${state.run}/irregularities`);
  const rejected = state.seen.filter((e) => e.status !== "passed").length;
  $("nodesign-text").textContent = (r.rough_edges
    ? `Rough edges make up ${Math.round(100 * r.rough_share)}% of the outline (worst ${r.worst_roughness_mm} mm from a straight or round edge; designed edges stay under ${r.roughness_limit_mm} mm). `
    : "") + `None of the ${state.seen.length} candidates stayed within the measurement limits (${rejected} rejected or failed), so the shape built straight from the measurements is shown.`;
  const rows = [
    ["Rough edges", r.rough_edges ? `${r.rough_length_mm} of ${r.perimeter_mm} mm` : "none", r.rough_share || 0],
    ["Missing material vs mirror image", r.missing_material_mm2 ? `${r.missing_material_mm2} mm²` : "none", null],
    ["Holes found", `${r.holes}${r.pattern_gaps ? `, ${r.pattern_gaps} gaps in a pattern` : ""}`, null],
  ];
  $("irregular-rows").innerHTML = rows.map(([label, value, share]) => `<div class="irregular-row"><div class="row-head">`
    + `<span>${label}</span><span class="row-value">${value}</span></div>`
    + (share !== null ? `<div class="bar"><span style="width:${Math.min(100, 100 * share).toFixed(0)}%"></span></div>` : "") + `</div>`).join("");
}

$("use-measured").addEventListener("click", () => showModel());
$("repair-again").addEventListener("click", () => {
  // Muse Wonder repairs the saved candidates again; a passing repair becomes the result.
  const status = $("repair-status");
  status.textContent = "Starting the repair…";
  $("repair-again").disabled = true;
  const stream = new EventSource(`/api/runs/${state.run}/repair/stream`);
  stream.addEventListener("progress", (m) => { status.textContent = JSON.parse(m.data).message; });
  stream.addEventListener("repair_started", (m) => wonderShow("repair", JSON.parse(m.data).seconds));
  stream.addEventListener("repair", (m) => {
    wonderCard.hide();
    const r = JSON.parse(m.data);
    streamItem(r.passed ? "REPAIRED" : "REPAIR", r.passed ? "tag-best" : "tag-bad",
      `repair round ${r.round} · Muse Wonder: ${r.passed ? "passed" : "not passed"}. ${r.diagnosis || ""}`, r.reasons.join(" | "));
  });
  stream.addEventListener("done", () => { stream.close(); wonderCard.hide(); $("repair-again").disabled = false; streamCandidates(); });
  stream.addEventListener("error", (m) => {
    wonderCard.hide();
    stream.close();
    $("repair-again").disabled = false;
    status.textContent = m.data ? `Not repaired: ${JSON.parse(m.data).message}` : "The repair needs MODEL_API_KEY in .env (Muse Wonder).";
  });
});

// ---------- edit ----------
const LABEL_FOR = [[/diam|hole|bore/, "hole"], [/thick|height|depth/, "thickness"], [/width/, "width"], [/length/, "length"]];
const labelKey = (name) => (LABEL_FOR.find(([pattern]) => pattern.test(name.toLowerCase())) || [])[1];
const prettyName = (name) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const unitFor = (name) => (/count|number|^n_/.test(name) ? "" : /angle/.test(name) ? "°" : " mm");
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

function currentValues() {
  const values = {};
  document.querySelectorAll("#sliders input[type=\"range\"]").forEach((input) => (values[input.name] = Number(input.value)));
  return values;
}

// The original part's values. While a matching part is shown the sliders are the matching part's own,
// so every new matching part (another card or another adapter preset) starts from the saved base.
const originalValues = () => state.matching?.base ?? currentValues();

function changedLabels() {
  return [...document.querySelectorAll("#sliders .slider.changed input[type=\"range\"]")].map((i) => labelKey(i.name)).filter(Boolean);
}

function postJSON(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", ...runHeaders() },
    body: JSON.stringify(body) });
}

// What the model, drawing and download requests add for a matching part (nothing for the original).
const matchQuery = (separator = "?") => (state.matching ? `${separator}match=${state.matching.kind}` : "");
const modelBody = () => (state.matching?.kind === "adapter"
  ? { parameters: currentValues(), base: state.matching.base, pattern: state.matching.pattern,
      outline: state.matching.outline, hole_style: state.matching.holeStyle || "exact" }
  : { parameters: currentValues(), base: state.matching?.base });

async function rebuild() {
  // Only the newest build may touch the screen: an older answer can arrive after it on a slow connection.
  const build = ++state.builds;
  const status = $("model-status");
  status.textContent = "Building…";
  const started = performance.now();
  const response = await postJSON(`/api/runs/${state.run}/model${matchQuery()}`, modelBody());
  if (build !== state.builds) return;
  if (!response.ok) {
    status.textContent = `Not built: ${(await response.json()).detail}`;
    $("fit-check").textContent = "";
    return;
  }
  const features = JSON.parse(response.headers.get("X-Model-Features") || "null");
  const model = await response.arrayBuffer();
  if (build !== state.builds) return;
  state.viewer.show(model, features);
  state.viewer.setChanged(changedLabels());
  if (features) {
    const [x0, y0, z0, x1, y1, z1] = features.box;
    $("model-size").innerHTML = `<strong>${(x1 - x0).toFixed(2)} × ${(y1 - y0).toFixed(2)} × ${(z1 - z0).toFixed(2)} mm</strong>`
      + ` · ${holeCountText(features)}`;
  }
  if (state.matching) await showAlignment(build);
  if (build !== state.builds) return;
  status.textContent = `Built in ${((performance.now() - started) / 1000).toFixed(1)} s`;
  // Slider moves in sim view re-run the check (the viewer animates the color change).
  if (assembly.view === "sim" && state.matching?.kind === "adapter") await runAssemblyCheck(false);
}

function holeCountText(features) {
  // The slotted adapter counts its slots (the /slotted answer says how many are slots vs shaped
  // copies); everywhere else the built round holes are counted.
  const counts = state.matching?.kind === "adapter" && state.matching.holeStyle === "slotted"
    ? state.matching.slottedInfo?.hole_counts : null;
  if (!counts) return `${features.holes.length} round holes`;
  const parts = [];
  if (counts.slots) parts.push(`${counts.slots} slot${counts.slots === 1 ? "" : "s"}`);
  if (counts.shaped) parts.push(`${counts.shaped} shaped hole${counts.shaped === 1 ? "" : "s"}`);
  return parts.join(" · ") || "no holes";
}

function slider(parameter) {
  const value = parameter.default;
  const span = Math.max(Math.abs(value) * Number(css("--slider-range")), 1);
  const unit = unitFor(parameter.name);
  // Design-parameter steps: 0.1 mm, or 0.05 mm for sub-millimetre values. Snapping runs on a grid
  // through the program's own value (in code, not the browser's step), so that value stays exact.
  const stepSize = Math.abs(value) < 1 ? 0.05 : 0.1;
  const snap = (v) => value + Math.round((v - value) / stepSize) * stepSize;
  const show = (v) => {
    const rounded = Math.round(v * 100) / 100;
    return String(Math.abs(v - rounded) < 1e-9 ? rounded : v);
  };
  const row = document.createElement("div");
  row.className = "slider";
  const min = (parameter.min ?? value - span).toFixed(2);
  const max = (parameter.max ?? value + span).toFixed(2);
  row.innerHTML = `<span class="slider-head"><span class="name">${prettyName(parameter.name)}</span>`
    + `<span class="mini-stepper"><button type="button" data-step="-1">\u2212</button>`
    + `<input type="text" inputmode="decimal" value="${value}"><span class="unit">${unit}</span>`
    + `<button type="button" data-step="1">+</button></span></span>
    <input type="range" name="${parameter.name}" min="${min}" max="${max}" step="0.01" value="${value}">
    <span class="range"><span>${min}</span><span class="default">PROGRAM: ${value}</span><span>${max}</span></span>`;
  const input = row.querySelector('input[type="range"]');
  const field = row.querySelector('input[type="text"]');
  input.dataset.default = value;
  const sync = () => {
    field.value = show(Number(input.value));
    row.classList.toggle("changed", Number(input.value) !== Number(input.dataset.default));
    state.viewer.setChanged(changedLabels());
  };
  input.addEventListener("input", () => {
    input.value = snap(Number(input.value)).toFixed(2);
    sync();
  });
  input.addEventListener("change", rebuild);
  const clamp = (v) => Math.min(Number(input.max), Math.max(Number(input.min), v));
  row.querySelectorAll(".mini-stepper button").forEach((button) => button.addEventListener("click", () => {
    input.value = show(clamp(snap(Number(input.value)) + stepSize * Number(button.dataset.step)));
    sync();
    rebuild();
  }));
  field.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      // Typed values apply exactly as typed (clamped to the slider range); only drags snap.
      const number = Number(field.value.replace(",", "."));
      input.value = Number.isFinite(number) ? clamp(number) : Number(input.value);
      sync();
      rebuild();
    } else if (event.key === "Escape") {
      field.value = show(Number(input.value));
      field.blur();
    }
  });
  field.addEventListener("blur", () => {
    field.value = show(Number(input.value));
  });
  return row;
}

function setSliders(values) {
  // Move sliders as a user would.
  for (const [name, value] of Object.entries(values)) {
    const input = document.querySelector(`#sliders input[name="${name}"]`);
    if (!input) continue;
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
}

async function showModel(sliderValues = {}) {
  setScreen("edit");
  if (!state.viewer) state.viewer = createViewer($("viewer"), { shiftRight: 140 });  // clear of the capture-fit inset
  state.viewer.resize();
  state.viewer.reset();
  $("model-status").textContent = "Building…";
  state.matching = null;
  state.splitWarning = null;
  updateSplitButtons();
  setMatchingLayout(null);
  state.viewer.showCompanion(null);
  state.viewer.showMating(null);
  state.winner = await getJSON(`/api/runs/${state.run}/winner`);
  const w = state.winner;
  $("model-program").textContent = `Program ${w.name}.py`;  // display name; w.program is the internal file
  $("model-source").textContent = w.note || `Source: ${sourceLabel(w.source)}`;
  $("fit-image").src = `/api/runs/${state.run}/capture-fit.png`;
  showCaptureFit(w);
  const sliders = $("sliders");
  sliders.innerHTML = "";
  w.parameters.forEach((p) => sliders.appendChild(slider(p)));
  setSliders(sliderValues);
  await rebuild();
  state.voiceChanges = [];
  $("voice-proposal")?.classList.add("hidden");
  await showCompletion();
}
$("to-model").addEventListener("click", () => showModel());

// ---------- matching part: a cover or spacer made from the built original, no model involved ----------
function setMatchingLayout(info) {
  // The Edit screen for a matching part (info) or the original (null).
  $("edit-panel").classList.toggle("matching-mode", !!info);
  $("matching-bar").classList.toggle("hidden", !info);
  $("matching-status").textContent = "";
  $("matching-status").classList.remove("warning");
  $("model-title").textContent = info ? `MATCHING · ${info.title}` : "ACTIVE MODEL";
  $("matching-name").textContent = info ? info.title : "";
  $("overlay-name").textContent = info ? info.title : "";
  ["overlay-view", "overlay-legend", "fit-check"].forEach((id) => $(id).classList.toggle("hidden", !info));
  if (!info) $("fit-check").textContent = "";  // back on the original: no leftover check line
  ["fit-image", "fit-table"].forEach((id) => $(id).classList.toggle("hidden", !!info));
  if (info) {
    $("fit-title").textContent = "TOP VIEW OVERLAY";
    $("fit-iou").textContent = "";
  }
  // The assembly panel and sim view belong to the adapter only; leaving it resets both.
  const adapter = !!info && state.matching?.kind === "adapter";
  if (!adapter && state.viewer?.assemblyActive?.()) state.viewer.hideAssembly();
  if (!adapter) resetAssembly();
  else {
    $("assembly-block").classList.remove("hidden");
    $("view-assembly").classList.remove("hidden");
  }
}

async function showMatching(kind) {
  const base = originalValues();
  $("model-status").textContent = "Building…";
  const failed = async (response) => {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await response.json()).detail}`;
    $("matching-status").classList.add("warning");
  };
  const info = await postJSON(`/api/runs/${state.run}/matching/${kind}`, { base });
  if (!info.ok) return failed(info);
  const original = await postJSON(`/api/runs/${state.run}/model`, { parameters: base });
  if (!original.ok) return failed(original);
  clearVoicePreview();
  state.winner = await info.json();
  state.matching = { kind, base };
  const w = state.winner;
  setMatchingLayout(w);
  $("model-program").textContent = `Program ${w.program}`;
  $("model-source").textContent = `Source: ${sourceLabel(w.source)}`;
  $("sliders").innerHTML = "";
  w.parameters.forEach((p) => $("sliders").appendChild(slider(p)));
  state.viewer.showSuggestion(null);
  state.viewer.showCompanion(await original.arrayBuffer(), "ORIGINAL");
  state.viewer.showMating(null);
  state.viewer.reset();  // frame both parts
  document.querySelectorAll(".view-tools button[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === "iso"));
  await rebuild();
}

function updateSplitButtons() {
  // A split gasket cannot be downloaded (its outline, DXF and 1:1 PDF would show only one piece):
  // buttons stay visible but disabled, with the warning as tooltip.
  document.querySelectorAll("button[data-format]").forEach((b) => {
    b.disabled = !!state.splitWarning;
    if (state.splitWarning) b.title = state.splitWarning;
    else b.removeAttribute("title");
  });
}

async function showAlignment(build) {
  // The computed check: both parts as built, drawn on top of each other, and their hole centers compared.
  const check = $("fit-check");
  const response = await postJSON(`/api/runs/${state.run}/matching/${state.matching.kind}/check`, modelBody());
  const answer = await response.json();
  if (build !== state.builds) return;
  if (!response.ok) {
    check.textContent = `Not checked: ${answer.detail}`;
    state.splitWarning = null;  // unknown pieces: let downloads try (the server refuses a split gasket)
    updateSplitButtons();
    check.classList.add("bad");
    return;
  }
  const { original, matching, alignment: a } = answer;
  state.splitWarning = (state.matching.kind === "spacer" && answer.warning) || null;
  updateSplitButtons();
  if (state.splitWarning) {  // hide the gasket overlay: one piece must not pose as the whole gasket
    check.textContent = state.splitWarning;
    check.classList.add("bad");
    drawOverlay(original, null);
    return;
  }
  drawOverlay(original, matching, answer.holes_b, answer.label_b, answer.holes_a);
  if (state.matching.kind === "adapter" && matching) updateAdapterGhosts(matching.thickness);
  const breakouts = a.breakouts === 1 ? "1 hole breaks through the edge" : `${a.breakouts} holes break through the edge`;
  check.innerHTML = !a.total ? "No holes to align"
    : `Holes aligned: ${a.aligned}/${a.total}${a.max_offset_mm === null ? "" : `, max offset ${a.max_offset_mm.toFixed(3)} mm`}`
      + (a.breakouts ? ` · <span class="fit-warning">${breakouts}</span>` : "")
      + (state.matching.kind === "adapter" ? adapterLine(answer) : "");
  check.classList.toggle("bad", a.aligned < a.total);
}

function drawOverlay(original, matching, holesB, labelB, holesA) {
  // Top view in mm (SVG's y runs down, so y is negated): the original see-through, the matching part as a line.
  const closed = (points) => `M${points.map(([x, y]) => `${x},${-y}`).join("L")}Z`;
  const circle = ([x, y], d) => `M${x - d / 2},${-y}a${d / 2},${d / 2} 0 1,0 ${d},0a${d / 2},${d / 2} 0 1,0 ${-d},0Z`;
  const shape = (p) => closed(p.outline) + p.holes.map((h) => (h.type === "circle" ? circle(h.center, h.diameter) : closed(h.points))).join("");
  const slotPath = (h) => {  // a capsule sampled as a polygon (slotted style: length/width/angle set)
    const straight = (h.length - h.width) / 2;
    const angle = (h.angle || 0) * Math.PI / 180;
    const ux = Math.cos(angle);
    const uy = Math.sin(angle);
    const points = [];
    for (const [end, start] of [[1, -90], [-1, 90]]) {
      const ex = h.x + ux * straight * end;
      const ey = h.y + uy * straight * end;
      for (let i = 0; i <= 8; i++) {
        const arc = (start + 180 * i / 8) * Math.PI / 180;
        const lx = Math.cos(arc) * h.width / 2;
        const ly = Math.sin(arc) * h.width / 2;
        points.push([ex + lx * ux - ly * uy, ey + lx * uy + ly * ux]);
      }
    }
    return closed(points);
  };
  const split = !matching;  // a split gasket hides its overlay: one piece must not pose as the whole
  matching = matching || { outline: [], holes: [], box: original.box };
  const x0 = Math.min(original.box[0], matching.box[0]);
  const y0 = Math.min(original.box[1], matching.box[1]);
  const x1 = Math.max(original.box[2], matching.box[2]);
  const y1 = Math.max(original.box[3], matching.box[3]);
  const margin = 0.04 * Math.max(x1 - x0, y1 - y0);
  const view = $("overlay-view");
  view.setAttribute("viewBox", `${x0 - margin} ${-y1 - margin} ${x1 - x0 + 2 * margin} ${y1 - y0 + 2 * margin}`);
  const bPath = (holesB || []).map((h) => (h.length === undefined ? circle([h.x, h.y], h.d) : slotPath(h))).join("");
  const aPath = (holesA || []).map(slotPath).join("");  // slotted style: pattern A's slots, dashed like B's

  view.innerHTML = `<path class="overlay-original" d="${shape(original)}"/><path class="overlay-matching" d="${shape(matching)}"/><path class="overlay-pattern-b" d="${bPath}"/><path class="overlay-pattern-a" d="${aPath}"/>`;
  $("overlay-b-item").classList.toggle("hidden", !holesB?.length);
  // A photo pattern's full summary stays in the line below; the legend keeps only its source.
  if (holesB?.length) $("overlay-b-label").textContent = `Pattern B · ${labelB.endsWith("from photo") ? "from photo" : labelB}`;
  $("overlay-a-item").classList.toggle("hidden", !holesA?.length);
  $("overlay-matching-item").classList.toggle("hidden", split);
}

document.querySelectorAll("#matching-choices button").forEach((b) => b.addEventListener("click", () =>
  (b.dataset.kind === "adapter" ? showAdapterPanel() : showMatching(b.dataset.kind))));
$("matching-back").addEventListener("click", () => showModel(state.matching.base));

// ---------- adapter plate: the original's holes plus a new hole pattern ----------
// Pattern B comes from a preset chip (fixed data, works everywhere) or free text parsed by Muse
// Spark Open (the reading is shown back and needs Apply); voice lands in the same text box and
// goes through the same parse + Apply path. Placement is deterministic; the outline is searched,
// then this enters the matching layout like a cover or spacer.
let adapterPattern = null;  // the parsed pattern waiting for Apply
let adapterPresets = null;  // preset chips, loaded once from the server

async function showAdapterPanel() {
  const panel = $("adapter-panel");
  panel.classList.toggle("hidden");
  if (panel.classList.contains("hidden")) return;
  clearAdapterPreview();
  $("adapter-status").textContent = "";
  $("adapter-status").classList.remove("warning");
  $("matching-status").textContent = "";
  $("matching-status").classList.remove("warning");
  if (!adapterPresets) {
    adapterPresets = (await getJSON("/api/adapter/presets")).presets;
    const box = $("adapter-presets");
    adapterPresets.forEach((preset) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.textContent = preset.label;
      chip.addEventListener("click", () => runAdapter(preset));
      box.appendChild(chip);
    });
  }
}

function clearAdapterPreview() {
  adapterPattern = null;
  $("adapter-parsed").classList.add("hidden");
  $("adapter-summary").textContent = "";
}

$("adapter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("adapter-input").value.trim();
  if (!text) return;
  clearAdapterPreview();
  $("adapter-status").textContent = "Reading the pattern · Muse Spark Open";
  $("adapter-status").classList.remove("warning");
  const response = await postJSON(`/api/runs/${state.run}/matching/adapter/parse`, { text });
  if (!response.ok) {
    $("adapter-status").textContent = (await response.json()).detail;
    $("adapter-status").classList.add("warning");
    return;
  }
  const answer = await response.json();
  adapterPattern = answer.pattern;
  $("adapter-summary").textContent = answer.summary;
  $("adapter-parsed").classList.remove("hidden");
  $("adapter-status").textContent = "Parsed by Muse Spark Open";
  $("adapter-status").classList.remove("warning");
});;
$("adapter-apply").addEventListener("click", () => { if (adapterPattern) runAdapter(adapterPattern); });
$("adapter-dismiss").addEventListener("click", () => {
  clearAdapterPreview();
  $("adapter-status").textContent = "Dismissed.";
  $("adapter-status").classList.remove("warning");
});

async function transcribePattern(blob) {
  // The same speech endpoint as voice editing; the transcript lands in the pattern box and is
  // parsed like typed text (shown back, needs Apply).
  $("adapter-status").textContent = "Transcribing · Muse Voice Transcribe";
  $("adapter-status").classList.remove("warning");
  const form = new FormData();
  form.append("audio", await toWav(blob), "command.wav");
  const response = await fetch(`/api/runs/${state.run}/voice/transcribe`, { method: "POST", body: form });
  if (!response.ok) {
    $("adapter-status").textContent = `Not transcribed: ${(await response.json()).detail}`;
    $("adapter-status").classList.add("warning");
    return;
  }
  const { transcript } = await response.json();
  $("adapter-input").value = transcript;
  if (transcript) $("adapter-form").requestSubmit();
  else $("adapter-status").textContent = "No speech was heard · Muse Voice Transcribe";
  $("adapter-status").classList.remove("warning");
}

$("adapter-mic").addEventListener("click", async () => {
  if (state.recorder) {  // second press: stop
    state.recorder.stop();
    return;
  }
  $("adapter-status").textContent = "Listening · press again to stop";
  $("adapter-status").classList.remove("warning");
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    $("adapter-status").textContent = `No microphone: ${error.message}`;
    $("adapter-status").classList.add("warning");
    return;
  }
  const chunks = [];
  const recorder = new MediaRecorder(stream);
  state.recorder = recorder;
  recorder.ondataavailable = (event) => chunks.push(event.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    clearTimeout(state.recordingTimer);
    state.recorder = null;
    $("adapter-mic").classList.remove("recording");
    await transcribePattern(new Blob(chunks, { type: recorder.mimeType }));
  };
  recorder.start();
  state.recordingTimer = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_RECORDING_MS);
  $("adapter-mic").classList.add("recording");
});

// ---------- adapter plate: pattern B measured from a photo of the mating part ----------
// Upload a photo of the mating part (with an ID-1 card next to it), click the part, and the
// existing live pipeline measures it (SAM 3.1 card + click mask, the frozen scale rule and hole
// finding); no candidate search runs for this photo. The measured holes are shown back and need
// Apply, then the existing placement and outline flow takes over.
const mating = { run: null, click: null, analysis: null, pattern: null, measuring: false };

function matingStatus(text, warning) {
  $("mating-status").textContent = text;
  $("mating-status").classList.toggle("warning", !!warning);
}

function resetMatingPhoto() {
  mating.run = null;
  mating.click = null;
  mating.analysis = null;
  mating.pattern = null;
  $("mating-svg").innerHTML = "";
  $("mating-scan").classList.add("hidden");
  $("mating-table").classList.add("hidden");
  $("mating-thickness-row").classList.add("hidden");
  $("mating-parsed").classList.add("hidden");
  $("mating-summary").textContent = "";
  $("mating-photo").removeAttribute("src");
}

$("adapter-photo").addEventListener("click", () => $("mating-file").click());
$("mating-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  clearAdapterPreview();
  resetMatingPhoto();
  $("mating-panel").classList.remove("hidden");
  matingStatus("Uploading…", false);
  const form = new FormData();
  form.append("photo", file);
  const response = await fetch(`/api/runs/${state.run}/matching/adapter/mating/upload`, { method: "POST", body: form });
  if (!response.ok) {
    matingStatus(`Upload failed: ${(await response.json()).detail}`, true);
    return;
  }
  mating.run = (await response.json()).name;
  const photo = $("mating-photo");
  photo.src = `/api/runs/${mating.run}/photo`;
  await photo.decode().catch(() => {});
  matingStatus("Click the mating part in the photo (not a hole).", false);
});

$("mating-photo").addEventListener("click", (event) => {
  if (!mating.run || mating.measuring || !event.target.naturalWidth) return;
  const box = event.target.getBoundingClientRect();
  mating.click = [Math.round((event.clientX - box.left) * (event.target.naturalWidth / box.width)),
                  Math.round((event.clientY - box.top) * (event.target.naturalHeight / box.height))];
  measureMating();
});

function matingError(message) {
  // SAM's failures in plain words (the technical text is not shown; nothing is guessed).
  if (/no card/i.test(message)) return "no ID-1 card was found in this photo — put a credit-card-size card next to the part and retake it";
  if (/no part/i.test(message)) return "nothing was found under the click — click on the part itself, not a hole and not the card";
  return message;
}

function measureMating() {
  mating.measuring = true;
  mating.analysis = null;
  mating.pattern = null;
  $("mating-svg").innerHTML = "";
  $("mating-table").classList.add("hidden");
  $("mating-thickness-row").classList.add("hidden");
  $("mating-parsed").classList.add("hidden");
  if (!reducedMotion()) $("mating-scan").classList.remove("hidden");
  const [x, y] = mating.click;
  const stream = new EventSource(`/api/live/${mating.run}/measure/stream?x=${x}&y=${y}`);
  stream.addEventListener("progress", (m) => matingStatus(JSON.parse(m.data).message, false));
  stream.addEventListener("analysis", async (m) => {
    stream.close();
    $("mating-scan").classList.add("hidden");
    mating.measuring = false;
    mating.analysis = JSON.parse(m.data);
    drawMating(mating.analysis);
    await fetchMatingPattern();
  });
  stream.addEventListener("error", (m) => {
    stream.close();
    $("mating-scan").classList.add("hidden");
    mating.measuring = false;
    matingStatus(m.data ? `Not measured: ${matingError(JSON.parse(m.data).message)}` : "The connection was lost.", true);
  });
}

function drawMating(a) {
  // The photo with the measured outline (draws itself) and the detected holes, numbered, one by
  // one — then the small "Measured" table. Purely visual: nothing waits for it.
  const svg = $("mating-svg");
  const [width, height] = a.image_size;
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  const points = (list) => list.map(([x, y]) => `${x},${y}`).join(" ");
  const ordered = [...a.holes].sort((p, q) => p.center_px[0] - q.center_px[0] || p.center_px[1] - q.center_px[1]);
  // SVG units are photo pixels; numbers stay readable by scaling like the capture canvas labels.
  const numberPx = 15 * (width / (svg.clientWidth || width));
  const contour = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  contour.setAttribute("points", points(a.outline_px));
  contour.setAttribute("class", "mating-contour");
  svg.appendChild(contour);
  if (!reducedMotion()) {
    const length = contour.getTotalLength();
    contour.style.strokeDasharray = `${length}`;
    contour.animate([{ strokeDashoffset: length }, { strokeDashoffset: 0 }],
      { duration: 900, easing: "ease-out", fill: "forwards" });
  }
  ordered.forEach((hole, i) => {
    const ring = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    ring.setAttribute("points", points(hole.contour_px));
    ring.setAttribute("class", "mating-hole");
    const number = document.createElementNS("http://www.w3.org/2000/svg", "text");
    number.setAttribute("x", hole.center_px[0]);
    number.setAttribute("y", hole.center_px[1]);
    number.setAttribute("class", "mating-number");
    number.setAttribute("font-size", numberPx.toFixed(1));
    number.textContent = i + 1;
    svg.append(ring, number);
    if (!reducedMotion()) {
      for (const element of [ring, number]) {
        element.animate([{ opacity: 0 }, { opacity: 1 }],
          { duration: 250, delay: 900 + 150 * i, fill: "backwards", easing: "ease-out" });
      }
    }
  });
  const rows = [["Measured", null], ["Outline", `${mm(a.outline_mm.length)} × ${mm(a.outline_mm.width)}`],
    [`Holes`, `${ordered.length} measured`],
    ...ordered.map((hole, i) => [`${i + 1}`, hole.size])];
  $("mating-table").innerHTML = tableHTML(rows);
  $("mating-table").classList.remove("hidden");
}

function matingThickness() {
  const value = Number(String($("mating-thickness").value).replace(",", "."));
  return Number.isFinite(value) && value >= 0.1 && value <= 100 ? value : null;
}

async function fetchMatingPattern() {
  // The measured holes as pattern B (deterministic, no model call); shown back, needs Apply.
  if (!mating.analysis.holes.length) {
    matingStatus("No holes were found in the mating part — the holes must show the background through them.", true);
    return;
  }
  const thickness = matingThickness();
  if (thickness === null) {
    matingStatus("Enter a mating thickness between 0.1 and 100 mm.", true);
    return;
  }
  matingStatus("Reading the hole pattern…", false);
  const response = await postJSON(`/api/runs/${state.run}/matching/adapter/mating/pattern`,
    { mating: mating.run, thickness });
  if (!response.ok) {
    matingStatus((await response.json()).detail, true);
    return;
  }
  const answer = await response.json();
  mating.pattern = answer.pattern;
  $("mating-summary").textContent = answer.summary;
  $("mating-parsed").classList.remove("hidden");
  $("mating-thickness-row").classList.remove("hidden");
  matingStatus("Measured · SAM 3.1", false);
}

$("mating-thickness").addEventListener("change", () => {
  // The entered thickness is stored with the mating run; re-reading is deterministic (no model).
  if (mating.analysis?.holes.length && !mating.measuring) fetchMatingPattern();
});
$("mating-dismiss").addEventListener("click", () => {
  mating.pattern = null;
  $("mating-parsed").classList.add("hidden");
  matingStatus("Dismissed.", false);
});

async function flyMatingHoles() {
  // The numbered holes travel from the photo panel toward the overlay inset (short and eased),
  // then the existing placement and outline flow runs. Purely visual: the pattern is decided.
  const box = document.querySelector(".fit-inset").getBoundingClientRect();
  const to = { x: box.left + box.width / 2, y: box.top + 120 };
  const flights = [...$("mating-svg").querySelectorAll(".mating-number")].map((label, i) => {
    const at = label.getBoundingClientRect();
    const dot = document.createElement("div");
    dot.className = "mating-fly";
    dot.textContent = label.textContent;
    dot.style.left = `${at.left + at.width / 2}px`;
    dot.style.top = `${at.top + at.height / 2}px`;
    document.body.appendChild(dot);
    const flight = dot.animate([
      { transform: "translate(0, 0) scale(1)", opacity: 1 },
      { transform: `translate(${to.x - at.left - at.width / 2}px, ${to.y - at.top - at.height / 2}px) scale(0.6)`, opacity: 0.2 },
    ], { duration: 600, delay: 90 * i, easing: "cubic-bezier(0.3, 0.7, 0.3, 1)", fill: "forwards" });
    return flight.finished.then(() => dot.remove()).catch(() => dot.remove());
  });
  await Promise.all(flights);
}

$("mating-apply").addEventListener("click", async () => {
  if (!mating.pattern) return;
  if (!reducedMotion()) await flyMatingHoles();
  runAdapter(mating.pattern, mating.run);
});

async function runAdapter(pattern, matingRun = null) {
  const base = originalValues();
  clearAdapterPreview();
  $("matching-status").textContent = "";
  $("matching-status").classList.remove("warning");
  $("model-status").textContent = "Placing the patterns…";
  const placed = await postJSON(`/api/runs/${state.run}/matching/adapter/place`, { base, pattern });
  if (!placed.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = (await placed.json()).detail;
    $("matching-status").classList.add("warning");
    return;
  }
  const place = await placed.json();
  const minWall = place.placement.walls.min;
  $("model-status").textContent = `Placed ${place.placement.candidate}`
    + (minWall === null ? "" : ` · min wall ${minWall.toFixed(1)} mm`) + " — finding the outline…";
  const outline = await postJSON(`/api/runs/${state.run}/matching/adapter/outline`,
    matingRun === null ? { base, pattern, outline: "auto" } : { base, pattern, outline: "auto", mating: matingRun });
  if (!outline.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await outline.json()).detail}`;
    $("matching-status").classList.add("warning");
    return;
  }
  const original = await postJSON(`/api/runs/${state.run}/model`, { parameters: base });
  if (!original.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await original.json()).detail}`;
    $("matching-status").classList.add("warning");
    return;
  }
  clearVoicePreview();
  state.winner = await outline.json();
  state.matching = { kind: "adapter", base, pattern, outline: "auto", mating: matingRun, holeStyle: "exact",
    exactInfo: state.winner, ghosts: { original: await original.arrayBuffer(), mating: null } };
  resetAssembly();
  const ghost = await postJSON(`/api/runs/${state.run}/matching/adapter/mating/plate`,
    matingRun === null ? { base, pattern, outline: "auto" } : { base, pattern, outline: "auto", mating: matingRun });
  if (ghost.ok) state.matching.ghosts.mating = await (await fetch((await ghost.json()).stl)).arrayBuffer();
  const w = state.winner;
  setMatchingLayout(w);
  $("model-program").textContent = `Program ${w.program}`;
  // The adapter source is already a full label ("Outline: …"); other sources get the "Source:" prefix.
  $("model-source").textContent = w.source.startsWith("Outline:") ? w.source : `Source: ${sourceLabel(w.source)}`;
  $("sliders").innerHTML = "";
  w.parameters.forEach((p) => $("sliders").appendChild(slider(p)));
  state.viewer.showSuggestion(null);
  state.viewer.reset();  // frame the parts
  document.querySelectorAll(".view-tools button[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === "iso"));
  await rebuild();
  runAssemblyCheck(false);  // the panel's verdict, in the background
}

function updateAdapterGhosts(thickness) {
  // Both ghosts exactly over their patterns (same XY as built), resting on the adapter's top face.
  const ghosts = state.matching?.ghosts;
  if (!ghosts) return;
  state.viewer.showCompanion(ghosts.original, "ORIGINAL", { overlay: true, liftZ: thickness });
  // A measured mating photo gives the real mating part; a preset or a typed pattern only a stand-in plate
  // (the same tag as in the assembly simulation).
  const tag = state.matching.mating ? "MATING PART" : "STAND-IN";
  state.viewer.showMating(ghosts.mating, ghosts.mating ? tag : null, thickness);
}

// ---------- adapter plate: assembly check simulation ----------
// Stacks the original, the adapter and the mating plate with fixed screws and reports every
// screw's computed interference volume per plate. Hole style (Exact/Slotted) switches the built
// adapter program; error case and screw sizes only re-run the check. All deterministic, no model.
const assembly = { view: "part", errorCase: "as_measured", screws: {}, data: null, running: 0, selectSignature: "" };
const stlCache = new Map();

function resetAssembly() {
  assembly.view = "part";
  assembly.errorCase = "as_measured";
  assembly.screws = {};
  assembly.data = null;
  assembly.selectSignature = "";
  $("view-assembly").classList.add("hidden");
  $("view-assembly").classList.remove("active");
  $("assembly-block").classList.add("hidden");
  $("assembly-verdict").classList.add("hidden");
  markVerdictChecking(false);
  $("assembly-screws").innerHTML = "";
  $("assembly-status").textContent = "";
  document.querySelectorAll("#assembly-style-row button").forEach((b) => b.classList.toggle("active", b.dataset.style === "exact"));
  document.querySelectorAll("#assembly-error-row button").forEach((b) => b.classList.toggle("active", b.dataset.error === "as_measured"));
}

async function fetchSTL(url) {
  if (!stlCache.has(url)) stlCache.set(url, (await fetch(url)).arrayBuffer());
  return stlCache.get(url);
}

function buildScrewSelects(data) {
  // One select per hole-size group; rebuilt only when the groups themselves change (not on every run).
  const signature = JSON.stringify(data.groups);
  if (signature === assembly.selectSignature) return;
  assembly.selectSignature = signature;
  const box = $("assembly-screws");
  box.innerHTML = "";
  for (const group of data.groups) {
    const row = document.createElement("label");
    row.className = "screw-row";
    row.textContent = `Ø${group.size.toFixed(2)} · ${group.holes.join(", ")}`;
    const select = document.createElement("select");
    select.setAttribute("aria-label", `screw size for holes ${group.holes.join(", ")}`);
    for (const size of ["M3", "M4", "M5", "M6", "none"]) {
      const option = document.createElement("option");
      option.value = size;
      option.textContent = size;
      select.appendChild(option);
    }
    select.value = assembly.screws[group.key] ?? group.default ?? "none";
    select.addEventListener("change", () => {
      const value = select.value === "none" ? null : select.value;
      if (value === group.default) delete assembly.screws[group.key];
      else assembly.screws[group.key] = value;
      runAssemblyCheck(false);
    });
    row.appendChild(select);
    box.appendChild(row);
  }
}

function markVerdictChecking(on) {
  // While the check re-runs, the shown verdict belongs to the previous settings: dim it and say so.
  $("assembly-verdict").classList.toggle("checking", on);
}

function updateVerdictBadge(data) {
  // The verdict, last: the overall line, then one computed line per blocked screw and skip note.
  const verdict = $("assembly-verdict");
  markVerdictChecking(false);
  verdict.classList.remove("hidden");
  verdict.classList.toggle("bad", data.verdict === "blocked");
  verdict.innerHTML = esc(data.message)
    + data.screws.filter((s) => s.verdict === "blocked").map((s) =>
      `<span class="verdict-sub">Hole ${esc(s.id)} blocked · ${s.depth_mm.toFixed(2)} mm overlap (${s.overlap_mm3.toFixed(2)} mm³)</span>`).join("")
    + data.skipped.map((g) => `<span class="verdict-sub">${esc(g.message)}</span>`).join("");
}

const simPlateTag = (plate) => (plate.name === "original" ? "ORIGINAL"
  : plate.name === "adapter" ? "ADAPTER" : (plate.label === "stand-in plate" ? "STAND-IN" : "MATING PART"));

async function showSim(intro) {
  const data = assembly.data;
  const jobs = [];
  for (const plate of data.plates) jobs.push(fetchSTL(plate.stl).then((buffer) => ({ kind: "plate", plate, buffer })));
  for (const screw of data.screws) {
    const artifacts = data.artifacts[screw.id];
    jobs.push(fetchSTL(artifacts.stl).then((buffer) => ({ kind: "screw", screw, buffer, clashes: [] })));
    for (const clash of artifacts.clashes) {
      jobs.push(fetchSTL(clash).then((buffer) => ({ kind: "clash", id: screw.id, buffer })));
    }
  }
  const parts = await Promise.all(jobs);
  const byId = {};
  for (const part of parts) if (part.kind === "screw") byId[part.screw.id] = part;
  for (const part of parts) if (part.kind === "clash") byId[part.id].clashes.push(part.buffer);
  $("assembly-verdict").classList.add("hidden");
  state.viewer.showAssembly({
    plates: parts.filter((p) => p.kind === "plate").map((p) => ({ buffer: p.buffer, tag: simPlateTag(p.plate) })),
    screws: parts.filter((p) => p.kind === "screw").map((p) => (
      { id: p.screw.id, x: p.screw.x, y: p.screw.y, buffer: p.buffer, verdict: p.screw.verdict,
        clashes: p.clashes })),
  }, { intro, onDone: () => updateVerdictBadge(assembly.data) });
}

async function runAssemblyCheck(intro) {
  // Recompute the check for the current style, error case, screws and slider values; in sim view
  // the viewer animates the result, else only the panel updates. Later runs cancel earlier ones.
  const run = ++assembly.running;
  $("assembly-status").textContent = "Checking the assembly…";
  $("assembly-status").classList.remove("warning");
  markVerdictChecking(true);  // the previous verdict stays readable but dimmed until the new one arrives
  let response;
  try {
    response = await postJSON(`/api/runs/${state.run}/matching/adapter/assembly`,
      { ...modelBody(), error_case: assembly.errorCase, screws: assembly.screws,
        ...(state.matching.mating ? { mating: state.matching.mating } : {}) });
  } catch (error) {
    if (run !== assembly.running) return;
    $("assembly-status").textContent = "The connection was lost.";
    $("assembly-status").classList.add("warning");
    $("assembly-verdict").classList.add("hidden");  // no verdict for the current settings
    markVerdictChecking(false);
    return;
  }
  if (run !== assembly.running) return;
  if (!response.ok) {
    $("assembly-status").textContent = (await response.json()).detail;
    $("assembly-status").classList.add("warning");
    $("assembly-verdict").classList.add("hidden");
    markVerdictChecking(false);
    return;
  }
  const data = await response.json();
  if (run !== assembly.running) return;
  assembly.data = data;
  buildScrewSelects(data);
  $("assembly-status").textContent = "";
  if (assembly.view === "sim") await showSim(intro);
  else updateVerdictBadge(data);
}

document.querySelectorAll("#assembly-error-row button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.error === assembly.errorCase) return;
  assembly.errorCase = b.dataset.error;
  document.querySelectorAll("#assembly-error-row button").forEach((o) => o.classList.toggle("active", o === b));
  runAssemblyCheck(false);
}));

$("assembly-show").addEventListener("click", () => {  // the visible twin of the toolbar's stacks icon
  if (assembly.view !== "sim") $("view-assembly").click();
});
$("view-assembly").addEventListener("click", async () => {
  if (assembly.view === "sim") {
    assembly.view = "part";
    $("view-assembly").classList.remove("active");
    state.viewer.hideAssembly();
    if (assembly.data) updateVerdictBadge(assembly.data);
    return;
  }
  assembly.view = "sim";
  $("view-assembly").classList.add("active");
  if (assembly.data) await showSim(true);
  else await runAssemblyCheck(true);
});

function loadAdapterProgram(info) {
  // Swap the adapter program (Exact ↔ Slotted variant): new sliders, rebuilt, ghosts follow.
  state.winner = info;
  $("model-program").textContent = `Program ${info.program}`;
  $("model-source").textContent = info.source.startsWith("Outline:") ? info.source : `Source: ${sourceLabel(info.source)}`;
  $("sliders").innerHTML = "";
  info.parameters.forEach((p) => $("sliders").appendChild(slider(p)));
  rebuild();
}

document.querySelectorAll("#assembly-style-row button").forEach((b) => b.addEventListener("click", async () => {
  const style = b.dataset.style;
  if (style === state.matching.holeStyle) return;
  if (style === "slotted") {
    markVerdictChecking(true);
    $("assembly-status").textContent = "Checking the slots…";
    $("assembly-status").classList.remove("warning");
    const { base, pattern, outline } = state.matching;
    const response = await postJSON(`/api/runs/${state.run}/matching/adapter/slotted`, { base, pattern, outline });
    if (!response.ok) {
      $("assembly-status").textContent = (await response.json()).detail;
      $("assembly-status").classList.add("warning");
      markVerdictChecking(false);  // Exact stays, and so does its verdict
      return;  // keep Exact, toggle untouched
    }
    state.matching.slottedInfo = await response.json();
  }
  state.matching.holeStyle = style;
  document.querySelectorAll("#assembly-style-row button").forEach((o) => o.classList.toggle("active", o === b));
  $("assembly-status").textContent = "";
  loadAdapterProgram(style === "exact" ? state.matching.exactInfo : state.matching.slottedInfo);
  if (assembly.view !== "sim") runAssemblyCheck(false);  // in sim view the rebuild re-runs it
}));

function adapterLine(answer) {
  // Pattern B as built: its label, hole count and the smallest edge margin, all computed.
  return ` · Pattern B: ${esc(answer.label_b)} (${answer.holes_b.length} holes, `
    + `min margin ${answer.min_margin_mm.toFixed(1)} mm)`;
}

function showCaptureFit(w) {
  // The inset as the capture fit: the program's own values (before any slider moves) against the
  // measurements and, if known, the truth.
  $("fit-title").textContent = "CAPTURE FIT";
  $("fit-iou").textContent = w.iou == null ? "" : `IoU ${w.iou.toFixed(4)}`;
  $("fit-table").innerHTML = tableHTML(resultRows({ fit_mm: w.fit_mm, ground_truth: w.ground_truth }));
}

async function showCompletion() {
  // The "possible break" card: shown when Muse Wonder suggested a completion and it was not ignored.
  const data = await getJSON(`/api/runs/${state.run}/completion`);
  const c = data.available ? data : null;
  state.completion = c;
  state.viewer.showSuggestion(null);
  showCaptureFit(state.winner);  // a shown suggestion turns the inset into the fracture view below
  const hidden = !c || c.broken === false || c.decision === "ignore";
  $("break-card").classList.toggle("hidden", hidden);
  $("break-again").classList.toggle("hidden", !(c && c.decision === "ignore"));
  if (hidden) return;
  if (!state.live && typeof c.seconds === "number") {  // replay: the recorded wait, briefly
    wonderCard.show("completion", c.seconds, $("break-card").parentNode, $("break-card"), "tab-parameters-only");
    await new Promise((resolve) => setTimeout(resolve, 1200));
    wonderCard.hide();
  }
  const applied = c.decision === "apply";
  const check = c.check || {};
  $("break-suggestion").textContent = c.suggestion || "";
  $("break-rationale").textContent = c.rationale || "";
  $("break-parts").innerHTML = partsHTML(c.parts || [], c.answers || {}, applied);
  $("break-note").textContent = !c.valid ? `Not offered: ${(check.reasons || ["no program returned"]).join("; ")}`
    : applied ? "Applied: the parameters below belong to the completed program."
    : [check.added_volume_mm3 > 0 ? `adds ${check.added_volume_mm3.toFixed(0)} mm³ (orange in the 3D view)` : "",
       check.removed_volume_mm3 > 0 ? `cuts ${check.removed_volume_mm3.toFixed(0)} mm³` : ""].filter(Boolean).join(", ");
  // The inset becomes the fracture view: the cues found, and how much material the suggestion adds.
  $("fit-title").textContent = "FRACTURE BOUNDARY";
  $("fit-iou").textContent = `${(c.cues || []).length} BREAK CUES`;
  const share = check.base_volume_mm3 ? (100 * ((check.added_volume_mm3 || 0) - (check.removed_volume_mm3 || 0)) / check.base_volume_mm3) : null;
  if (share !== null) {
    $("fit-table").innerHTML += tableHTML([["Added material", `${share >= 0 ? "+" : "−"}${Math.abs(share).toFixed(1)}% vol.`]]);
  }
  $("break-apply").disabled = !c.valid;
  $("break-apply").innerHTML = applied ? "Undo" : `<span class="icon">check</span>Apply`;
  $("break-ignore").classList.toggle("hidden", applied);
  if (!applied && c.valid && c.added_stl) {
    state.viewer.showSuggestion(await (await fetch(c.added_stl)).arrayBuffer(),
      `SUGGESTED FEATURE · +${(check.added_volume_mm3 || 0).toFixed(0)} mm³`);
  }
}

function partsHTML(parts, answers, locked) {
  // What the suggestion adds: a measured | estimated summary, then one question per estimated number
  // (with the suggested value in a stepper) and per optional feature (off unless ticked).
  const escape = (text) => escapeAttribute(text || "");
  const isFlag = (p) => /^(add|restore)_/.test(p.name) && (p.value === 0 || p.value === 1);
  const item = (p) => escape(prettyName(p.name)) + (isFlag(p) ? "" : ` ${p.value}`) + (p.method ? ` · ${escape(p.method)}` : "");
  const measured = parts.filter((p) => p.basis === "measured");
  const asked = parts.filter((p) => p.basis !== "measured");
  const value = (p) => answers[p.name] || p.value;
  const stepper = (p) => `<span class="mini-stepper"><button data-step="-1" data-for="${escape(p.name)}" ${locked ? "disabled" : ""}>−</button>`
    + `<input type="text" inputmode="decimal" data-part="${escape(p.name)}" value="${value(p)}" ${locked ? "disabled" : ""}>`
    + `<span class="unit">mm</span><button data-step="1" data-for="${escape(p.name)}" ${locked ? "disabled" : ""}>+</button></span>`;
  const html = [];
  if (parts.length) {
    html.push(`<div class="break-basis"><div><span class="basis-label">Measured</span>`
      + `<span class="basis-items">${measured.map(item).join(", ") || "–"}</span></div>`
      + `<div><span class="basis-label estimated">Estimated</span>`
      + `<span class="basis-items">${asked.map((p) => escape(prettyName(p.name))).join(", ") || "–"}</span></div></div>`);
  }
  for (const p of asked) {
    const optional = p.basis === "optional";
    const label = optional
      ? `<label class="question-label"><input type="checkbox" data-optional="${escape(p.name)}" ${answers[p.name] > 0 ? "checked" : ""} ${locked ? "disabled" : ""}>${escape(prettyName(p.name))}?</label>`
      : `<span class="question-label">${escape(prettyName(p.name))}?</span>`;
    // Short on the card (the parameter as a question); Wonder's full question on hover.
    const sub = (optional ? `suggested ${p.value} mm · not visible, off unless ticked` : `suggested ${p.value} mm`) + (p.method ? ` · ${escape(p.method)}` : "");
    html.push(`<div class="question" title="${escape(p.question)}"><span class="question-text">${label}`
      + `<span class="question-sub">${sub}</span></span>${stepper(p)}</div>`);
  }
  return html.join("");
}

document.addEventListener("click", (event) => {
  // The card's small steppers: ±0.5 mm.
  const button = event.target.closest(".mini-stepper button");
  if (!button || !event.target.closest("#break-parts")) return;  // sliders handle their own steppers
  const input = document.querySelector(`#break-parts input[data-part="${button.dataset.for}"]`);
  const number = Number(String(input.value).replace(",", ".")) || 0;
  input.value = Math.max(0, number + 0.5 * Number(button.dataset.step)).toFixed(2).replace(/\.?0+$/, "");
});

function partAnswers() {
  // The user's answers: estimated values as typed; optional features their value if ticked, else 0 (left out).
  const values = {};
  document.querySelectorAll("#break-parts input[data-part]").forEach((input) => {
    const number = Number(String(input.value).replace(",", "."));
    if (Number.isFinite(number) && number >= 0) values[input.dataset.part] = number;
  });
  document.querySelectorAll("#break-parts input[data-optional]").forEach((box) => {
    if (!box.checked) values[box.dataset.optional] = 0;
  });
  return values;
}

async function decideCompletion(decision, values = null) {
  // apply / ignore / undo. Own photos: the server writes decision.json. Samples: the server only checks the
  // answer and returns it ("stored": "browser"); this browser keeps it and sends it with later requests.
  const response = await postJSON(`/api/runs/${state.run}/completion/${decision}`, values ? { values } : {});
  if (!response.ok) return (await response.json()).detail;
  const answer = await response.json();
  if (answer.stored === "browser") {
    storeDecision(state.run, answer.decision ? { decision: answer.decision, values: answer.answers || {} } : null);
  }
  return null;
}

$("break-apply").addEventListener("click", async () => {
  const undo = state.completion.decision === "apply";
  const error = await decideCompletion(undo ? "undo" : "apply", undo ? null : partAnswers());
  if (error) {
    $("break-note").textContent = `Not applied: ${error}`;
    return;
  }
  await showModel();  // the result program changed: new parameters, new model
});
$("break-ignore").addEventListener("click", async () => {
  await decideCompletion("ignore");
  await showCompletion();
});
$("break-again").addEventListener("click", async () => {  // after Ignore: bring the suggestion back
  await decideCompletion("undo");
  await showCompletion();
});

$("reset-parameters").addEventListener("click", () => {
  document.querySelectorAll("#sliders .slider").forEach((row) => {
    const input = row.querySelector('input[type="range"]');
    input.value = input.dataset.default;
    row.querySelector(".mini-stepper input").value = input.value;
    row.classList.remove("changed");
  });
  rebuild();
});

document.querySelectorAll(".view-tools button[data-view]").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.view !== "fit") document.querySelectorAll(".view-tools button[data-view]").forEach((o) => o.classList.toggle("active", o === b));
  state.viewer?.setView(b.dataset.view);
}));
document.querySelector("[data-labels]").addEventListener("click", (event) => {
  const button = event.currentTarget;
  button.classList.toggle("active");
  state.viewer?.setLabelsVisible(button.classList.contains("active"));
});

async function downloadFile(format, status = $("download-status")) {
  if (state.splitWarning && state.matching?.kind === "spacer") {
    status.textContent = `Not built: ${state.splitWarning}`;
    return;
  }
  status.textContent = `Preparing ${format.toUpperCase()}…`;
  const response = await postJSON(`/api/runs/${state.run}/download?format=${format}${matchQuery("&")}`, modelBody());
  if (!response.ok) {
    status.textContent = `Not built: ${(await response.json()).detail}`;
    return;
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition"))?.[1] ?? `part.${format}`;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(await response.blob());
  link.download = name;
  link.click();
  URL.revokeObjectURL(link.href);
  status.textContent = `Saved ${name}.`;
}
document.querySelectorAll(".exports button").forEach((b) => b.addEventListener("click", () => downloadFile(b.dataset.format)));
document.querySelectorAll("#screen-export [data-format]").forEach((b) =>
  b.addEventListener("click", () => downloadFile(b.dataset.format, $("export-status"))));

// ---------- voice editing: a command becomes named parameter changes, shown first, applied on Apply ----------
function sliderRow(name) {
  return document.querySelector(`#sliders input[name="${name}"]`)?.closest(".slider");
}

function clearVoicePreview() {
  state.voiceChanges = [];
  $("voice-proposal")?.classList.add("hidden");
  document.querySelectorAll("#sliders .slider.pending").forEach((row) => {
    row.classList.remove("pending");
    const input = row.querySelector('input[type="range"]');
    row.querySelector(".mini-stepper input").value = input.value;
    row.querySelector(".voice-tag")?.remove();
    row.querySelector(".range .default").textContent = `PROGRAM: ${input.dataset.default}`;
  });
  ["length", "width", "thickness", "hole"].forEach((key) => state.viewer?.previewLabel(key, null));
  state.viewer?.setChanged(changedLabels());
}

function showVoiceChanges(result) {
  // The proposal in the card and on each slider (old value struck, new value, the difference); nothing is built yet.
  clearVoicePreview();
  state.voiceChanges = result.changes;
  $("voice-said").textContent = `“${result.command}”`;
  $("voice-note").textContent = result.note || "";
  if (!result.changes.length) return;
  const fmt = (v) => Number(v.toFixed(2));
  $("voice-changes").innerHTML = result.changes.map((c) => `<div class="voice-change"><span class="icon accent">edit</span>`
    + `${prettyName(c.name)} <s>${fmt(c.from)}</s> → <strong>${fmt(c.to)}${unitFor(c.name)}</strong></div>`).join("");
  $("voice-proposal").classList.remove("hidden");
  for (const c of result.changes) {
    const row = sliderRow(c.name);
    if (!row) continue;
    row.classList.add("pending");
    row.querySelector(".name").insertAdjacentHTML("beforeend", `<span class="voice-tag">VOICE EDIT</span>`);
    row.querySelector(".mini-stepper input").value = fmt(c.to);  // from → to stays in the card and the TARGET line
    const delta = c.to - c.from;
    row.querySelector(".range .default").textContent = `TARGET: ${fmt(c.to)} (${delta >= 0 ? "+" : "−"}${fmt(Math.abs(delta))})`;
  }
  for (const c of result.changes) {  // the 3D label shows old -> new until Apply
    const key = labelKey(c.name);
    if (key === "hole") {
      state.viewer.previewLabel("hole", (built) => `${built.split("Ø")[0]}Ø${fmt(c.from)} → Ø${fmt(c.to)} mm`);  // keeps "4× "
    } else if (key) {
      state.viewer.previewLabel(key, `${fmt(c.from)} → ${fmt(c.to)} mm`);
    }
  }
  const pending = result.changes.map((c) => labelKey(c.name)).filter(Boolean);
  state.viewer.setChanged([...changedLabels(), ...pending]);
}

async function interpretCommand(command) {
  $("voice-state").textContent = "Understanding · Muse Spark Open";
  $("voice-note").textContent = "";
  const response = await postJSON(`/api/runs/${state.run}/voice/interpret`, { command, parameters: currentValues() });
  $("voice-state").textContent = "Voice edit · Muse Spark Open";
  if (!response.ok) {
    $("voice-note").textContent = `Not understood: ${(await response.json()).detail}`;
    return;
  }
  showVoiceChanges(await response.json());
}

$("voice-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const command = $("voice-input").value.trim();
  if (command) interpretCommand(command);
});

$("voice-apply").addEventListener("click", async () => {
  // Move the sliders to the proposed values (widening a slider's range if needed), then rebuild once.
  const changes = state.voiceChanges || [];
  clearVoicePreview();
  for (const c of changes) {
    const input = document.querySelector(`#sliders input[name="${c.name}"]`);
    if (!input) continue;
    if (c.to > Number(input.max)) input.max = (c.to * 1.25).toFixed(2);
    if (c.to < Number(input.min)) input.min = Math.max(0, c.to * 0.75).toFixed(2);
    input.value = c.to;
    input.dispatchEvent(new Event("input"));
  }
  $("voice-note").textContent = changes.length ? `Applied ${changes.length} change${changes.length > 1 ? "s" : ""}.` : "";
  await rebuild();
});
$("voice-dismiss").addEventListener("click", () => {
  clearVoicePreview();
  $("voice-note").textContent = "Dismissed.";
});

// Speech: press the mic to record, press again to stop (at most 15 s). The recording is turned into the WAV
// Muse Voice Transcribe accepts (mono, 16-bit PCM, 24 kHz), transcribed, then interpreted like a typed command.
const MAX_RECORDING_MS = 15000;
const WAV_RATE = 24000;

async function toWav(blob) {
  const decoded = await new AudioContext().decodeAudioData(await blob.arrayBuffer());
  const offline = new OfflineAudioContext(1, Math.ceil(decoded.duration * WAV_RATE), WAV_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);  // mixes down to mono and resamples to 24 kHz
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (offset, s) => [...s].forEach((c, i) => view.setUint8(offset + i, c.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, WAV_RATE, true); view.setUint32(28, WAV_RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, samples.length * 2, true);
  samples.forEach((s, i) => view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 0x7fff, true));
  return new Blob([view], { type: "audio/wav" });
}

async function transcribeRecording(blob) {
  $("voice-state").textContent = "Transcribing · Muse Voice Transcribe";
  const form = new FormData();
  form.append("audio", await toWav(blob), "command.wav");
  const response = await fetch(`/api/runs/${state.run}/voice/transcribe`, { method: "POST", body: form });
  if (!response.ok) {
    $("voice-state").textContent = "Voice edit · Muse Spark Open";
    $("voice-note").textContent = `Not transcribed: ${(await response.json()).detail}`;
    return;
  }
  const { transcript } = await response.json();
  $("voice-input").value = transcript;
  if (transcript) await interpretCommand(transcript);
  else { $("voice-state").textContent = "Voice edit · Muse Voice Transcribe + Spark Open"; $("voice-note").textContent = "No speech was heard."; }
}

$("voice-mic").addEventListener("click", async () => {
  if (state.recorder) {  // second press: stop
    state.recorder.stop();
    return;
  }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    $("voice-note").textContent = `No microphone: ${error.message}`;
    return;
  }
  const chunks = [];
  const recorder = new MediaRecorder(stream);
  state.recorder = recorder;
  recorder.ondataavailable = (event) => chunks.push(event.data);
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    clearTimeout(state.recordingTimer);
    state.recorder = null;
    $("voice-mic").classList.remove("recording");
    await transcribeRecording(new Blob(chunks, { type: recorder.mimeType }));
  };
  recorder.start();
  state.recordingTimer = setTimeout(() => recorder.state === "recording" && recorder.stop(), MAX_RECORDING_MS);
  $("voice-mic").classList.add("recording");
  $("voice-state").textContent = "Listening · press again to stop";
  $("voice-note").textContent = "";
});

const SETUP_URL = "https://github.com/pnomokok/reversecad#live-mode-your-own-photos";  // README: keys and live mode

function offNote(element, feature, plural = false) {
  // Replace a control this server cannot run with one calm line and a link to the setup steps.
  const s = plural ? "" : "s";
  const where = state.config.demo ? `work${s} in the local app with API keys` : `need${s} API keys in .env`;
  const note = document.createElement("p");
  // Keep the replaced control's tab class, so the note shows on the same panel tab only.
  note.className = ["off-note", ...[...element.classList].filter((name) => name.startsWith("tab-"))].join(" ");
  note.innerHTML = `${feature} ${where} · <a href="${SETUP_URL}" target="_blank" rel="noopener">Setup</a>`;
  element.replaceWith(note);
}

function applyConfig(config) {
  // What this server cannot do (the online demo has no API keys) is not shown at all, only a note.
  state.config = config;
  if (!config.live) {
    offNote(document.querySelector(".dropzone"), "Your own photos", true);
    offNote($("repair-again"), "Repair");
    offNote($("mating-row"), "Pattern from a photo");
  }
  if (!config.voice) {
    offNote($("voice-card"), "Voice editing");
    offNote($("adapter-textbox"), "Free text, voice and Spark Open outlines", true);
  } else if (!config.speech) {  // typing works; speaking also needs MODEL_API_KEY
    $("voice-mic").remove();
    $("adapter-mic").remove();
    $("adapter-mic-hint").remove();
    $("voice-said").textContent = "Type a command, for example \"make the holes 2 mm bigger\".";
  } else {
    $("voice-mic").disabled = false;
    $("voice-mic").title = "Press to speak a command, press again to stop";
    $("voice-said").textContent = "Press the mic and say a command, or type it and press Enter.";
    $("adapter-mic").disabled = false;
    $("adapter-mic").title = "Press to speak a pattern, press again to stop";
  }
}

// ---------- export: technical drawing and packages ----------
async function showExport() {
  if (!state.winner) await showModel();
  updateSplitButtons();
  setScreen("export");
  const response = await postJSON(`/api/runs/${state.run}/drawing${matchQuery()}`, modelBody());
  if (!response.ok) {
    $("export-status").textContent = `Not built: ${(await response.json()).detail}`;
    return;
  }
  const data = await response.json();
  const p = data.profile;
  const [x0, y0, x1, y1] = p.box;
  $("export-name").innerHTML = `<strong>${data.name}</strong> · ${(x1 - x0).toFixed(2)} × ${(y1 - y0).toFixed(2)} × ${p.thickness.toFixed(2)} mm`
    + ` · ${data.program} (${data.source})`;
  $("drawing-facts").textContent = `${p.holes.length} holes · outline ${p.outline.length} points · all dimensions in mm`;
  $("drawing").innerHTML = drawingSVG(data);
  $("fact-stl").textContent = state.viewer ? `${state.viewer.triangleCount().toLocaleString("en-US")} triangles` : "";
  $("fact-dxf").textContent = `${1 + p.holes.length} closed contours`;
  const program = await postJSON(`/api/runs/${state.run}/download?format=py${matchQuery("&")}`, modelBody());
  const source = await program.text();
  $("code-preview").textContent = source.split("\n").filter((line) => line.trim()).slice(0, 8).join("\n");
  $("fact-py").textContent = `${state.winner.parameters.length} named parameters`;
}

function drawingSVG(data) {
  // A drawing sheet (420 × 297 units): top view with overall dimensions and hole callouts, front view with
  // the thickness and hidden holes, a hole table from the lower-left corner, and a title block.
  const p = data.profile;
  const [x0, y0, x1, y1] = p.box;
  const [length, width, thickness] = [x1 - x0, y1 - y0, p.thickness];
  const area = { left: 46, top: 42, width: 250, height: 150 };
  const s = Math.min(area.width / length, area.height / (width + thickness + 30));
  const ox = area.left + (area.width - length * s) / 2;
  const oy = area.top;
  const X = (x) => ox + (x - x0) * s;
  const Y = (y) => oy + (y1 - y) * s;
  const fmt = (v) => v.toFixed(2);
  const out = [];
  const box = (text, cx, cy, size = 7) => {
    const w = text.length * size * 0.62 + 4;
    out.push(`<rect class="box" x="${cx - w / 2}" y="${cy - size * 0.75}" width="${w}" height="${size * 1.5}"/>`
      + `<text class="value" x="${cx}" y="${cy + size * 0.36}" text-anchor="middle" style="font-size:${size}px">${text}</text>`);
  };
  const arrowhead = (x, y, dx, dy) => {
    const n = Math.hypot(dx, dy) || 1;
    const [ux, uy] = [dx / n, dy / n];
    out.push(`<polygon class="arrow" points="${x},${y} ${x - ux * 2.4 - uy * 0.8},${y - uy * 2.4 + ux * 0.8} ${x - ux * 2.4 + uy * 0.8},${y - uy * 2.4 - ux * 0.8}"/>`);
  };
  const dimension = (ax, ay, bx, by, text) => {
    out.push(`<line class="dim" x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}"/>`);
    arrowhead(ax, ay, ax - bx, ay - by);
    arrowhead(bx, by, bx - ax, by - ay);
    box(text, (ax + bx) / 2, (ay + by) / 2);
  };
  out.push(`<rect class="frame" x="5" y="5" width="410" height="287"/>`);
  out.push(`<text class="view-title" x="${area.left}" y="22">VIEW A · TOP</text>`);

  // Top view: outline, holes, centerlines, and the origin of the hole table.
  out.push(`<polygon class="part" points="${p.outline.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")}"/>`);
  p.holes.forEach((hole) => {
    if (hole.type === "circle") {
      const [cx, cy, r] = [X(hole.center[0]), Y(hole.center[1]), (hole.diameter / 2) * s];
      out.push(`<circle class="cut" cx="${cx}" cy="${cy}" r="${r}"/>`);
      out.push(`<path class="center" d="M${cx - r - 2},${cy}H${cx + r + 2}M${cx},${cy - r - 2}V${cy + r + 2}"/>`);
    } else {
      out.push(`<polygon class="cut" points="${hole.points.map(([x, y]) => `${X(x)},${Y(y)}`).join(" ")}"/>`);
    }
  });
  out.push(`<path class="origin" d="M${X(x0) - 3},${Y(y0)}H${X(x0) + 3}M${X(x0)},${Y(y0) - 3}V${Y(y0) + 3}"/>`);
  out.push(`<text class="small" x="${X(x0) - 4}" y="${Y(y0) + 6}" text-anchor="end">0,0</text>`);

  // Overall dimensions: length above, width on the right.
  const top = Y(y1) - 12;
  out.push(`<path class="ext" d="M${X(x0)},${Y(y1) - 2}V${top - 2}M${X(x1)},${Y(y1) - 2}V${top - 2}"/>`);
  dimension(X(x0), top, X(x1), top, fmt(length));
  const right = X(x1) + 16;
  out.push(`<path class="ext" d="M${X(x1) + 2},${Y(y1)}H${right + 2}M${X(x1) + 2},${Y(y0)}H${right + 2}"/>`);
  dimension(right, Y(y1), right, Y(y0), fmt(width));

  // Hole callouts: one per diameter, with a leader to one hole of the group.
  const groups = new Map();
  p.holes.filter((h) => h.type === "circle").forEach((h) => {
    const key = h.diameter.toFixed(2);
    groups.set(key, [...(groups.get(key) || []), h]);
  });
  let row = 0;
  for (const [diameter, holes] of groups) {
    const h = holes.reduce((a, b) => (b.center[0] + b.center[1] > a.center[0] + a.center[1] ? b : a));
    const [hx, hy] = [X(h.center[0]), Y(h.center[1])];
    const lx = X(x1) + 40;
    const ly = Y(y1) - 2 + row * 12;
    out.push(`<path class="dim" d="M${hx},${hy}L${lx - 18},${ly}"/>`);
    box(`${holes.length > 1 ? `${holes.length}× ` : ""}Ø${diameter} THRU`, lx + 16, ly, 6);
    row += 1;
  }

  // Front view (third-angle: below the top view): thickness and hidden holes.
  const fy = Y(y0) + 22;
  const ft = Math.max(thickness * s, 2);
  out.push(`<text class="view-title" x="${area.left}" y="${fy - 4}">VIEW B · FRONT</text>`);
  out.push(`<rect class="part" x="${X(x0)}" y="${fy}" width="${length * s}" height="${ft}"/>`);
  p.holes.forEach((hole) => {
    const xs = hole.type === "circle" ? [hole.center[0] - hole.diameter / 2, hole.center[0] + hole.diameter / 2]
      : [Math.min(...hole.points.map((q) => q[0])), Math.max(...hole.points.map((q) => q[0]))];
    xs.forEach((x) => out.push(`<line class="hidden-line" x1="${X(x)}" y1="${fy}" x2="${X(x)}" y2="${fy + ft}"/>`));
  });
  const fl = X(x0) - 12;
  out.push(`<path class="ext" d="M${X(x0) - 2},${fy}H${fl - 2}M${X(x0) - 2},${fy + ft}H${fl - 2}"/>`);
  out.push(`<line class="dim" x1="${fl}" y1="${fy - 6}" x2="${fl}" y2="${fy + ft + 6}"/>`);
  arrowhead(fl, fy, 0, 1);
  arrowhead(fl, fy + ft, 0, -1);
  box(fmt(thickness), fl - 18, fy + ft / 2);

  // Hole table (from the lower-left corner, 0,0) and, for a shaped outline, its corners.
  const tx = 12;
  const ty = 222;
  const span = (h, k) => [Math.min(...h.points.map((q) => q[k])), Math.max(...h.points.map((q) => q[k]))];
  const rows = p.holes.map((h, i) => (h.type === "circle"
    ? [`H${i + 1}`, fmt(h.center[0] - x0), fmt(h.center[1] - y0), `Ø${fmt(h.diameter)}`]
    : [`H${i + 1}`, fmt(span(h, 0)[0] - x0), fmt(span(h, 1)[0] - y0),
       `${fmt(span(h, 0)[1] - span(h, 0)[0])} × ${fmt(span(h, 1)[1] - span(h, 1)[0])}`]));
  const columns = [0, 18, 50, 82];
  out.push(`<text class="view-title" x="${tx}" y="${ty - 4}">HOLE TABLE · from 0,0</text>`);
  [["HOLE", "X", "Y", "SIZE"], ...rows].slice(0, 12).forEach((cells, i) => {
    cells.forEach((cell, j) => out.push(`<text class="table-text" x="${tx + columns[j]}" y="${ty + 5 + i * 6.4}">${cell}</text>`));
    out.push(`<line class="table-line" x1="${tx}" y1="${ty + 6.8 + i * 6.4}" x2="${tx + 120}" y2="${ty + 6.8 + i * 6.4}"/>`);
  });
  if (p.outline.length > 4 && p.outline.length <= 16) {
    const cx = tx + 128;
    out.push(`<text class="view-title" x="${cx}" y="${ty - 4}">OUTLINE CORNERS</text>`);
    p.outline.slice(0, 12).forEach(([x, y], i) => out.push(`<text class="table-text" x="${cx}" y="${ty + 5 + i * 6.4}">`
      + `C${i + 1}  ${fmt(x - x0)}, ${fmt(y - y0)}</text>`));
  }

  // Title block.
  const bx = 262;
  const by = 236;
  out.push(`<rect class="frame" x="${bx}" y="${by}" width="148" height="51"/>`);
  out.push(`<path class="table-line" d="M${bx},${by + 17}H${bx + 148}M${bx},${by + 34}H${bx + 148}M${bx + 74},${by + 17}V${by + 51}"/>`);
  out.push(`<text class="small" x="${bx + 3}" y="${by + 5}">PART NAME</text><text class="block-title" x="${bx + 3}" y="${by + 13}">${data.name}</text>`);
  out.push(`<text class="small" x="${bx + 3}" y="${by + 22}">SCALE</text><text class="value" x="${bx + 3}" y="${by + 30}">1:1</text>`);
  out.push(`<text class="small" x="${bx + 77}" y="${by + 22}">UNITS</text><text class="value" x="${bx + 77}" y="${by + 30}">mm</text>`);
  out.push(`<text class="small" x="${bx + 3}" y="${by + 39}">PROGRAM</text><text class="table-text" x="${bx + 3}" y="${by + 46}">${data.program}</text>`);
  out.push(`<text class="small" x="${bx + 77}" y="${by + 39}">DATE · PROJECTION</text><text class="table-text" x="${bx + 77}" y="${by + 46}">`
    + `${new Date().toISOString().slice(0, 10)} · 3rd angle</text>`);
  return out.join("");
}

// ---------- start ----------
(async () => {
  setScreen("capture");
  updateProcedure();
  applyConfig(await getJSON("/api/config"));
  const { runs, samples } = await getJSON("/api/runs");
  $("example-list").innerHTML = samples.map((n) => `<button data-run="${n}">${n}</button>`).join("");
  const local = runs.filter((name) => !samples.includes(name));
  $("your-runs").classList.toggle("hidden", !local.length);
  $("your-runs-summary").textContent = `Your runs (${local.length})`;
  $("your-runs-list").innerHTML = local.map((n) => `<button data-run="${n}">${n}</button>`).join("");
  document.querySelectorAll("#example-list button, #your-runs-list button")
    .forEach((b) => b.addEventListener("click", () => chooseRun(b.dataset.run)));

  // Deep link for screenshots and recordings: ?run=A_light&step=search (?step=parts needs no run)
  const params = new URLSearchParams(location.search);
  const run = params.get("run");
  if (params.get("step") === "parts") await openParts();
  else if (run && runs.includes(run)) await openDeepLink(run, params);
  document.body.dataset.ready = "true";  // webapp/screenshot.py waits for this
})();

async function openRunFromParts(name) {
  // A gallery card opens the run where the work happens: the existing replay flow's edit screen.
  await chooseRun(name);
  await measure();
  await streamCandidates();
  await showModel();
}

function openParts() {
  return showParts($("parts-grid"), $("parts-status"), { setScreen, openRun: openRunFromParts });
}

async function openDeepLink(run, params) {
  const step = params.get("step") || "capture";
  state.round = params.get("round");  // an older saved round, for the search screen only
  await chooseRun(run);
  if (step === "capture") return;
  await measure();
  if (step === "measure") return;
  await streamCandidates();
  if (step !== "edit" && step !== "export" && step !== "match") return;
  await showModel();
  if (params.get("match") === "adapter") {  // &pattern=N picks the preset (screenshots, videos)
    await showAdapterPanel();
    await runAdapter(adapterPresets[Number(params.get("pattern")) || 0] || adapterPresets[0]);
  } else if (params.get("match")) await showMatching(params.get("match"));
  if (step === "match" || params.get("match")) setScreen("match");  // a match flow lands on its tab
  if (step === "export") {
    await showExport();
    return;
  }
  // &set=length:95,hole_diameter:7 moves sliders as a user would (to show a changed state).
  const changes = (params.get("set") || "").split(",").filter(Boolean).map((pair) => pair.split(":"));
  setSliders(Object.fromEntries(changes));
  if (changes.length) await rebuild();
  // &say=make the holes 2 mm bigger types a voice command (shows the proposal, not applied).
  if (params.get("say")) {
    $("voice-input").value = params.get("say");
    await interpretCommand(params.get("say"));
  }
}
