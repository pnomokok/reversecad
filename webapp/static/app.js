// ReverseCAD front end. Three screens (layout adapted from the Stitch screens in design/):
//   Capture: upload a photo or try an example, click the part, set the thickness, measure.
//   Search:  candidates arrive one by one (server-sent events) into a grid; the selected one grows to 2×2.
//   Edit:    the result in 3D with dimension labels, a slider per named parameter, and downloads.
// Every number shown comes from the back end or from the built model; nothing is made up for display.
// ?run=<name>&step=capture|measure|search|edit opens a saved run on that screen (screenshots, videos);
// with step=edit, &set=<parameter>:<value>,... also moves sliders; with step=edit or export, &match=cover|spacer
// opens that matching part first.
import { createViewer } from "./viewer.js";

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

async function getJSON(url) {
  const response = await fetch(url);
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
  state.screen = screen;
  document.querySelectorAll("#steps button, #rail button").forEach((b) => b.classList.toggle("active", b.dataset.screen === screen));
  ["capture", "search", "edit", "export"].forEach((name) => $(`screen-${name}`).classList.toggle("hidden", name !== screen));
  if (screen === "capture") render();
  if (screen === "edit" && state.viewer) state.viewer.resize();
  updateHeader();
}

function enableSteps() {
  const canEdit = !!(state.done && state.done.result_source && !state.done.result_source.startsWith("none"));
  document.querySelectorAll('[data-screen="search"]').forEach((b) => (b.disabled = !state.analysis));
  document.querySelectorAll('[data-screen="edit"], [data-screen="export"]').forEach((b) => (b.disabled = !canEdit));
}

document.querySelectorAll("#steps button, #rail button").forEach((button) =>
  button.addEventListener("click", () => {
    if (button.dataset.screen === "export") showExport();
    else if (button.dataset.screen === "edit" && !state.winner) showModel();
    else setScreen(button.dataset.screen);
  }));

function updateHeader() {
  const chip = $("run-chip");
  chip.classList.toggle("hidden", !state.run);
  chip.textContent = state.run ? `${state.live ? "Live" : "Example"} · ${state.run}` : "";
  const searching = state.screen === "search" && !!state.analysis;
  $("progress").classList.toggle("hidden", !searching);
  if (!searching) return;
  const total = state.done ? state.done.candidate_count : state.expected;
  const count = state.seen.filter((e) => !e.label).length;  // requested candidates only, not repairs (R1, R2)
  $("progress-label").textContent = state.done ? "Search finished"
    : state.live ? "Generating with Muse Spark · Checking against the SAM 3.1 mask" : "Replaying a saved candidate round";
  $("progress-count").textContent = total ? `${Math.round((100 * count) / total)}% | ${count} / ${total}` : `${count}`;
  $("progress-fill").style.width = total ? `${(100 * count) / total}%` : "0";
}

// ---------- capture: photo and overlay ----------
function scale() {
  return canvas.width / (canvas.clientWidth || canvas.width);
}

function polygon(points, color, width, closed = true, glow = false) {
  context.save();
  context.beginPath();
  points.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
  if (closed) context.closePath();
  context.strokeStyle = color;
  context.lineWidth = width * scale();
  if (glow) {
    context.shadowColor = css("--color-selected-glow");
    context.shadowBlur = 16 * scale();
  }
  context.stroke();
  context.restore();
}

function callout(text, x, y, fontPx = Number(css("--callout-font-px"))) {
  // A dimension box: dark fill, white border, white monospace text, centered on (x, y).
  const s = scale();
  context.font = `700 ${fontPx * s}px ${css("--font-mono")}`;
  const width = context.measureText(text).width + 16 * s;
  const height = fontPx * 1.6 * s;
  context.fillStyle = css("--color-callout-bg");
  context.fillRect(x - width / 2, y - height / 2, width, height);
  context.strokeStyle = css("--color-dimension");
  context.lineWidth = Number(css("--callout-border-px")) * s;
  context.strokeRect(x - width / 2, y - height / 2, width, height);
  context.fillStyle = css("--color-dimension");
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, x, y + 1 * s);
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

function orientedBox(points) {
  // The part's box along its own main axis (principal axes of the outline points): center, axes, corners.
  const n = points.length;
  const [cx, cy] = [points.reduce((s, p) => s + p[0], 0) / n, points.reduce((s, p) => s + p[1], 0) / n];
  let [sxx, syy, sxy] = [0, 0, 0];
  for (const [x, y] of points) { sxx += (x - cx) ** 2; syy += (y - cy) ** 2; sxy += (x - cx) * (y - cy); }
  const angle = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  const u = [Math.cos(angle), Math.sin(angle)];
  const v = [-u[1], u[0]];
  const along = (p, axis) => (p[0] - cx) * axis[0] + (p[1] - cy) * axis[1];
  const us = points.map((p) => along(p, u));
  const vs = points.map((p) => along(p, v));
  const [u0, u1, v0, v1] = [Math.min(...us), Math.max(...us), Math.min(...vs), Math.max(...vs)];
  const at = (a, b) => [cx + u[0] * a + v[0] * b, cy + u[1] * a + v[1] * b];
  return { center: [cx, cy], u, v, corners: [at(u0, v0), at(u1, v0), at(u1, v1), at(u0, v1)] };
}

function dimensionBeside(p, q, center, gap) {
  // The dimension line for edge p→q, moved by `gap` to the side away from `center`.
  const length = Math.hypot(q[0] - p[0], q[1] - p[1]) || 1;
  let [nx, ny] = [-(q[1] - p[1]) / length, (q[0] - p[0]) / length];
  if (((p[0] + q[0]) / 2 - center[0]) * nx + ((p[1] + q[1]) / 2 - center[1]) * ny < 0) [nx, ny] = [-nx, -ny];
  const [a, b] = [[p[0] + nx * gap, p[1] + ny * gap], [q[0] + nx * gap, q[1] + ny * gap]];
  return { a, b, middle: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2] };
}

let occupied = [];  // boxes of the labels drawn so far in this render: [left, top, right, bottom]

function labelBox(text, x, y, fontPx = Number(css("--callout-font-px"))) {
  const s = scale();
  context.font = `700 ${fontPx * s}px ${css("--font-mono")}`;
  const [w, h] = [context.measureText(text).width + 16 * s, fontPx * 1.6 * s];
  return [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
}

function fits(box) {
  const pad = 4 * scale();
  const inPhoto = box[0] > 0 && box[1] > 0 && box[2] < canvas.width && box[3] < canvas.height;
  return inPhoto && !occupied.some((o) => box[0] < o[2] + pad && box[2] > o[0] - pad && box[1] < o[3] + pad && box[3] > o[1] - pad);
}

function edgeDimension(edges, center, text, gap) {
  // Draw the dimension beside one of two parallel edges: outside the shape if its label fits in the
  // photo without covering another label, else inside (gap toward the center).
  const options = [...edges.map(([p, q]) => dimensionBeside(p, q, center, gap)),
                   ...edges.map(([p, q]) => dimensionBeside(p, q, center, -gap))];
  const found = options.find((d) => fits(labelBox(text, ...d.middle)));
  const { a, b } = found || options[0];
  const middle = found ? found.middle : clampInside(text, options[0].middle);  // never cut off by the photo edge
  dimensionLine(a[0], a[1], b[0], b[1]);
  callout(text, middle[0], middle[1]);
  occupied.push(labelBox(text, ...middle));
}

function sidePairs(corners) {
  // The two pairs of opposite edges of a quadrilateral, each pair ordered: upper/left edge first.
  const edges = corners.map((p, i) => [p, corners[(i + 1) % 4]]);
  const length = (e) => Math.hypot(e[1][0] - e[0][0], e[1][1] - e[0][1]);
  const middle = (e) => [(e[0][0] + e[1][0]) / 2, (e[0][1] + e[1][1]) / 2];
  const longPair = length(edges[0]) >= length(edges[1]) ? [edges[0], edges[2]] : [edges[1], edges[3]];
  const shortPair = longPair[0] === edges[0] ? [edges[1], edges[3]] : [edges[0], edges[2]];
  longPair.sort((a, b) => middle(a)[1] - middle(b)[1]);  // upper long edge first
  shortPair.sort((a, b) => middle(b)[0] - middle(a)[0]);  // right short edge first
  return { longPair, shortPair };
}

function drawCard(corners) {
  // The card's known size (ID-1, 85.60 × 53.98 mm) beside one long and one short edge.
  const center = [corners.reduce((s, p) => s + p[0], 0) / 4, corners.reduce((s, p) => s + p[1], 0) / 4];
  const { longPair, shortPair } = sidePairs(corners);
  const gap = 40 * scale();
  edgeDimension(longPair, center, "85.60 mm", gap);
  edgeDimension([shortPair[1], shortPair[0]], center, "53.98 mm", gap);  // left short edge first
}

function drawMeasurements(a) {
  const s = scale();
  occupied = [];
  polygon(a.card_corners_px, css("--color-overlay-card"), 2);
  polygon(a.outline_px, css("--color-overlay-part"), Number(css("--overlay-line-width")), true, true);
  a.holes.forEach((hole) => polygon(hole.contour_px, css("--color-overlay-hole"), 2));

  const box = orientedBox(a.outline_px);
  if (state.click) occupied.push([state.click[0] - 70 * s, state.click[1] - 30 * s, state.click[0] + 70 * s, state.click[1] + 62 * s]);

  // The part's outline first (its labels matter most), along its own axes; then the holes; then the card.
  const { longPair, shortPair } = sidePairs(box.corners);
  edgeDimension(longPair, box.center, mm(a.outline_mm.length), 56 * s);
  edgeDimension(shortPair, box.center, mm(a.outline_mm.width), 56 * s);
  holeGroups(a.holes).forEach((group) => drawHoleGroup(group, box));
  drawCard(a.card_corners_px);
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

function drawHoleGroup(group, box) {
  // One label for the group, at the first free spot near the holes, with a thin leader to each hole.
  const s = scale();
  const text = holeGroupText(group);
  const centers = group.holes.map((h) => h.center_px);
  const middle = [centers.reduce((t, c) => t + c[0], 0) / centers.length, centers.reduce((t, c) => t + c[1], 0) / centers.length];
  const step = 48 * s;
  const spots = [middle, ...[1, -1, 2, -2].map((k) => [middle[0] + box.v[0] * step * k, middle[1] + box.v[1] * step * k]),
                 ...centers.map(([x, y]) => [x + (box.center[0] - x) * 0.35, y + (box.center[1] - y) * 0.35])];
  const [x, y] = spots.find((p) => fits(labelBox(text, ...p, 16))) || clampInside(text, spots[0], 16);
  context.strokeStyle = css("--color-overlay-hole");
  context.lineWidth = 1.5 * s;
  context.beginPath();
  for (const [hx, hy] of centers) { context.moveTo(x, y); context.lineTo(hx, hy); }
  context.stroke();
  callout(text, x, y, 16);
  occupied.push(labelBox(text, x, y, 16));
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
  if (state.analysis) drawMeasurements(state.analysis);
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
  for (const key of Object.keys(steps)) $(`step-${key}`).classList.toggle("done", steps[key]);
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
  document.querySelectorAll("#example-list button").forEach((b) => b.classList.toggle("active", b.dataset.run === name));
  state.image = await loadImage(`/api/runs/${name}/photo`);
  state.click = (await getJSON(`/api/runs/${name}/info`)).click_px;  // the example's own click
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
  document.querySelectorAll("#example-list button").forEach((b) => b.classList.remove("active"));
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
  if (state.analysis) resetResults();  // a new click means a new measurement
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

function showAnalysis(a) {
  state.analysis = a;
  $("analyze").classList.add("hidden");
  $("to-candidates").classList.remove("hidden");
  render();
  updateProcedure();
  updateCaptureBars();
  enableSteps();
}

function measureLive() {
  return new Promise((resolve) => {
    const status = $("capture-status");
    const [x, y] = state.click;
    const stream = new EventSource(`/api/live/${state.run}/measure/stream?x=${x}&y=${y}`);
    stream.addEventListener("progress", (m) => (status.textContent = JSON.parse(m.data).message));
    stream.addEventListener("analysis", (m) => {
      stream.close();
      status.textContent = "";
      showAnalysis(JSON.parse(m.data));
      resolve();
    });
    stream.addEventListener("error", (m) => {
      stream.close();
      status.textContent = m.data ? `Failed: ${JSON.parse(m.data).message}` : "The connection was lost.";
      resolve();
    });
  });
}

async function measure() {
  $("analyze").disabled = true;
  $("analyze-label").textContent = "Measuring…";
  if (state.live) await measureLive();
  else showAnalysis(await getJSON(`/api/runs/${state.run}/analysis`));
  $("analyze-label").textContent = "Measure";
  $("analyze").disabled = false;
}
$("analyze").addEventListener("click", measure);

// ---------- search ----------
const escapeAttribute = (text) => String(text).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
const percent = (model, truth) => `${model - truth >= 0 ? "+" : "−"}${Math.abs((100 * (model - truth)) / truth).toFixed(1)}%`;

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
    rows.push(["vs ground truth", null]);  // a heading row
    for (const key of ["length", "width"]) {
      const [model, real] = truth[key];
      rows.push([key === "length" ? "Length" : "Width", `${model.toFixed(2)} vs ${real.toFixed(2)} (${percent(model, real)})`]);
    }
    if (truth.holes && truth.holes.length) {
      const worst = Math.max(...truth.holes.map(([model, real]) => Math.abs(model - real)));
      rows.push(["Holes", `Ø within ${mm(worst)}`]);
    }
  }
  if (event.parameters != null) rows.push(["Parameters", event.parameters]);
  return rows;
}

const MODEL_NAMES = { "sam-3.1": "SAM 3.1", "meta-models/muse-spark-open-1026": "Muse Spark Open", "muse-wonder-1.0": "Muse Wonder" };

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
  const picture = event.silhouette ? `<img src="${event.silhouette}" alt="candidate ${event.candidate} silhouette">` : "";
  const reason = event.reasons.length  // plain words on the card, the technical text on hover
    ? `<div class="reason" title="${escapeAttribute(event.reasons.join("\n"))}">${event.plain_reasons[0]}</div>` : "";
  const status = { passed: "PASS", rejected: "REJECTED", failed: "FAILED" }[event.status];
  card.innerHTML = `<header><span>#${idOf(event)}</span><span class="status-chip">${status}</span></header>`
    + `<div class="shape">${picture}${reason}</div><div class="scores">${scoreLine(event)}</div>`;
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
    ? `<div class="truth-line">vs ground truth: ${event.ground_truth.length[0].toFixed(2)} × ${event.ground_truth.width[0].toFixed(2)}`
      + ` vs ${event.ground_truth.length[1].toFixed(2)} × ${event.ground_truth.width[1].toFixed(2)} mm`
      + ` (${percent(...event.ground_truth.length)} / ${percent(...event.ground_truth.width)})</div>` : "";
  card.innerHTML = `<div class="winner-head"><span class="winner-id"><span class="winner-number">#${idOf(event)}</span>${event.label ? "REPAIRED" : "BEST MATCH"}</span>`
    + `<span class="winner-chip">Selected · ${event.parameters} params</span></div>`
    + `<div class="shape">${length}<img src="${event.silhouette}" alt="selected candidate silhouette"></div>`
    + `<div class="winner-scores"><div><span class="label">Overlap (IoU)</span><span class="big-accent">IoU ${event.iou.toFixed(4)}</span></div>`
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
  const now = new Date();
  const time = `${pad2(now.getHours())}:${pad2(now.getMinutes())}:${pad2(now.getSeconds())}.${String(now.getMilliseconds()).padStart(3, "0")}`;
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

function streamCandidates() {
  return new Promise((resolve) => {
    if (state.stream) state.stream.close();
    state.done = null;
    state.winner = null;
    state.seen = [];
    state.expected = state.live ? Number($("candidate-count").value) : null;
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
    state.stream = new EventSource(state.live
      ? `/api/live/${state.run}/candidates/stream?count=${count}&thickness=${thickness() ?? 3}`
      : `/api/runs/${state.run}/candidates/stream${state.round ? `?round=${state.round}` : ""}`);
    state.stream.addEventListener("progress", (m) => streamItem("…", "tag-ok", JSON.parse(m.data).message));
    state.stream.addEventListener("repair", (m) => {
      // A Muse Wonder repair round: its diagnosis, and whether its program passed the same checks.
      const r = JSON.parse(m.data);
      streamItem(r.passed ? "REPAIRED" : "REPAIR", r.passed ? "tag-best" : "tag-bad",
        `repair round ${r.round} · Muse Wonder: ${r.passed ? `passed, IoU ${r.iou.toFixed(4)}` : "not passed"}. ${r.diagnosis || ""}`,
        r.reasons.join("\n"));
    });
    state.stream.addEventListener("candidate", (m) => {
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
      state.done = JSON.parse(m.data);
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
      streamItem("ERROR", "tag-bad", m.data ? JSON.parse(m.data).message : "The candidate stream stopped unexpectedly.");
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
  stream.addEventListener("repair", (m) => {
    const r = JSON.parse(m.data);
    streamItem(r.passed ? "REPAIRED" : "REPAIR", r.passed ? "tag-best" : "tag-bad",
      `repair round ${r.round} · Muse Wonder: ${r.passed ? "passed" : "not passed"}. ${r.diagnosis || ""}`, r.reasons.join(" | "));
  });
  stream.addEventListener("done", () => { stream.close(); $("repair-again").disabled = false; streamCandidates(); });
  stream.addEventListener("error", (m) => {
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

function changedLabels() {
  return [...document.querySelectorAll("#sliders .slider.changed input[type=\"range\"]")].map((i) => labelKey(i.name)).filter(Boolean);
}

function postJSON(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

// What the model, drawing and download requests add for a matching part (nothing for the original).
const matchQuery = (separator = "?") => (state.matching ? `${separator}match=${state.matching.kind}` : "");
const modelBody = () => (state.matching?.kind === "adapter"
  ? { parameters: currentValues(), base: state.matching.base, pattern: state.matching.pattern, outline: state.matching.outline }
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
      + ` · ${features.holes.length} round holes`;
  }
  if (state.matching) await showAlignment(build);
  if (build !== state.builds) return;
  status.textContent = `Built in ${((performance.now() - started) / 1000).toFixed(1)} s`;
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
  state.winner = await getJSON(`/api/runs/${state.run}/winner`);
  const w = state.winner;
  $("model-program").textContent = `Program ${w.program}`;
  $("model-source").textContent = w.note || `Source: ${w.source}`;
  $("fit-image").src = `/api/runs/${state.run}/capture-fit.png`;
  $("fit-iou").textContent = w.iou == null ? "" : `IoU ${w.iou.toFixed(4)}`;
  // The program's own values (before any slider moves) against the measurements and, if known, the truth.
  $("fit-table").innerHTML = tableHTML(resultRows({ fit_mm: w.fit_mm, ground_truth: w.ground_truth }));
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
  $("matching-choices").classList.add("hidden");
  $("matching-status").textContent = "";
  $("model-title").textContent = info ? `MATCHING · ${info.title}` : "ACTIVE MODEL";
  $("matching-name").textContent = info ? info.title : "";
  $("overlay-name").textContent = info ? info.title : "";
  ["overlay-view", "overlay-legend", "fit-check"].forEach((id) => $(id).classList.toggle("hidden", !info));
  ["fit-image", "fit-table"].forEach((id) => $(id).classList.toggle("hidden", !!info));
  if (info) {
    $("fit-title").textContent = "TOP VIEW OVERLAY";
    $("fit-iou").textContent = "";
  }
}

async function showMatching(kind) {
  const base = currentValues();
  $("model-status").textContent = "Building…";
  const failed = async (response) => {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await response.json()).detail}`;
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
  $("model-source").textContent = `Source: ${w.source}`;
  $("sliders").innerHTML = "";
  w.parameters.forEach((p) => $("sliders").appendChild(slider(p)));
  state.viewer.showSuggestion(null);
  state.viewer.showCompanion(await original.arrayBuffer(), "ORIGINAL");
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
  drawOverlay(original, matching, answer.holes_b, answer.label_b);
  const breakouts = a.breakouts === 1 ? "1 hole breaks through the edge" : `${a.breakouts} holes break through the edge`;
  check.innerHTML = !a.total ? "No holes to align"
    : `Holes aligned: ${a.aligned}/${a.total}${a.max_offset_mm === null ? "" : `, max offset ${a.max_offset_mm.toFixed(3)} mm`}`
      + (a.breakouts ? ` · <span class="fit-warning">${breakouts}</span>` : "")
      + (state.matching.kind === "adapter" ? adapterLine(answer) : "");
  check.classList.toggle("bad", a.aligned < a.total);
}

function drawOverlay(original, matching, holesB, labelB) {
  // Top view in mm (SVG's y runs down, so y is negated): the original see-through, the matching part as a line.
  const closed = (points) => `M${points.map(([x, y]) => `${x},${-y}`).join("L")}Z`;
  const circle = ([x, y], d) => `M${x - d / 2},${-y}a${d / 2},${d / 2} 0 1,0 ${d},0a${d / 2},${d / 2} 0 1,0 ${-d},0Z`;
  const shape = (p) => closed(p.outline) + p.holes.map((h) => (h.type === "circle" ? circle(h.center, h.diameter) : closed(h.points))).join("");
  const split = !matching;  // a split gasket hides its overlay: one piece must not pose as the whole
  matching = matching || { outline: [], holes: [], box: original.box };
  const x0 = Math.min(original.box[0], matching.box[0]);
  const y0 = Math.min(original.box[1], matching.box[1]);
  const x1 = Math.max(original.box[2], matching.box[2]);
  const y1 = Math.max(original.box[3], matching.box[3]);
  const margin = 0.04 * Math.max(x1 - x0, y1 - y0);
  const view = $("overlay-view");
  view.setAttribute("viewBox", `${x0 - margin} ${-y1 - margin} ${x1 - x0 + 2 * margin} ${y1 - y0 + 2 * margin}`);
  const bPath = (holesB || []).map((h) => circle([h.x, h.y], h.d)).join("");
  const bLabel = holesB?.length ? `<text class="overlay-b-label" x="${holesB[0].x}" y="${-holesB[0].y - holesB[0].d / 2 - 1}" text-anchor="middle">${esc(labelB || "")}</text>` : "";
  view.innerHTML = `<path class="overlay-original" d="${shape(original)}"/><path class="overlay-matching" d="${shape(matching)}"/><path class="overlay-pattern-b" d="${bPath}"/>${bLabel}`;
  $("overlay-b-item").classList.toggle("hidden", !holesB?.length);
  if (holesB?.length) $("overlay-b-label").textContent = `Pattern B · ${labelB}`;
  $("overlay-matching-item").classList.toggle("hidden", split);
}

$("matching-open").addEventListener("click", () => $("matching-choices").classList.toggle("hidden"));
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
  $("matching-choices").classList.add("hidden");
  if (panel.classList.contains("hidden")) return;
  clearAdapterPreview();
  $("adapter-status").textContent = "";
  $("matching-status").textContent = "";
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
  $("adapter-status").textContent = "";
});
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
  const form = new FormData();
  form.append("audio", await toWav(blob), "command.wav");
  const response = await fetch(`/api/runs/${state.run}/voice/transcribe`, { method: "POST", body: form });
  if (!response.ok) {
    $("adapter-status").textContent = `Not transcribed: ${(await response.json()).detail}`;
    return;
  }
  const { transcript } = await response.json();
  $("adapter-input").value = transcript;
  if (transcript) $("adapter-form").requestSubmit();
  else $("adapter-status").textContent = "No speech was heard.";
}

$("adapter-mic").addEventListener("click", async () => {
  if (state.recorder) {  // second press: stop
    state.recorder.stop();
    return;
  }
  $("adapter-status").textContent = "Listening · press again to stop";
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    $("adapter-status").textContent = `No microphone: ${error.message}`;
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

async function runAdapter(pattern) {
  const base = currentValues();
  clearAdapterPreview();
  $("adapter-panel").classList.add("hidden");
  $("model-status").textContent = "Placing the patterns…";
  const placed = await postJSON(`/api/runs/${state.run}/matching/adapter/place`, { base, pattern });
  if (!placed.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = (await placed.json()).detail;
    return;
  }
  const place = await placed.json();
  const minWall = place.placement.walls.min;
  $("model-status").textContent = `Placed ${place.placement.candidate}`
    + (minWall === null ? "" : ` · min wall ${minWall.toFixed(1)} mm`) + " — finding the outline…";
  const outline = await postJSON(`/api/runs/${state.run}/matching/adapter/outline`, { base, pattern, outline: "auto" });
  if (!outline.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await outline.json()).detail}`;
    return;
  }
  const original = await postJSON(`/api/runs/${state.run}/model`, { parameters: base });
  if (!original.ok) {
    $("model-status").textContent = "";
    $("matching-status").textContent = `Not built: ${(await original.json()).detail}`;
    return;
  }
  clearVoicePreview();
  state.winner = await outline.json();
  state.matching = { kind: "adapter", base, pattern, outline: "auto" };
  const w = state.winner;
  setMatchingLayout(w);
  $("model-program").textContent = `Program ${w.program}`;
  $("model-source").textContent = `Source: ${w.source}`;
  $("sliders").innerHTML = "";
  w.parameters.forEach((p) => $("sliders").appendChild(slider(p)));
  state.viewer.showSuggestion(null);
  state.viewer.showCompanion(await original.arrayBuffer(), "ORIGINAL");
  state.viewer.reset();  // frame both parts
  document.querySelectorAll(".view-tools button[data-view]").forEach((b) => b.classList.toggle("active", b.dataset.view === "iso"));
  await rebuild();
}

function adapterLine(answer) {
  // Pattern B as built: its label, hole count and the smallest edge margin, all computed.
  return ` · Pattern B: ${esc(answer.label_b)} (${answer.holes_b.length} holes, `
    + `min margin ${answer.min_margin_mm.toFixed(1)} mm)`;
}

async function showCompletion() {
  // The "possible break" card: shown when Muse Wonder suggested a completion and it was not ignored.
  const data = await getJSON(`/api/runs/${state.run}/completion`);
  const c = data.available ? data : null;
  state.completion = c;
  state.viewer.showSuggestion(null);
  $("fit-title").textContent = "CAPTURE FIT";
  const hidden = !c || c.broken === false || c.decision === "ignore";
  $("break-card").classList.toggle("hidden", hidden);
  if (hidden) return;
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
  const item = (p) => escape(prettyName(p.name)) + (isFlag(p) ? "" : ` ${p.value}`);
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
    const sub = optional ? `suggested ${p.value} mm · not visible, off unless ticked` : `suggested ${p.value} mm`;
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

$("break-apply").addEventListener("click", async () => {
  const undo = state.completion.decision === "apply";
  const response = await fetch(`/api/runs/${state.run}/completion/${undo ? "undo" : "apply"}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(undo ? {} : { values: partAnswers() }),
  });
  if (!response.ok) {
    $("break-note").textContent = `Not applied: ${(await response.json()).detail}`;
    return;
  }
  await showModel();  // the result program changed: new parameters, new model
});
$("break-ignore").addEventListener("click", async () => {
  await fetch(`/api/runs/${state.run}/completion/ignore`, { method: "POST" });
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
}));

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
  const response = await fetch(`/api/runs/${state.run}/voice/interpret`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ command, parameters: currentValues() }),
  });
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
  else $("voice-note").textContent = "No speech was heard.";
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
  note.className = "off-note";
  note.innerHTML = `${feature} ${where} · <a href="${SETUP_URL}" target="_blank" rel="noopener">Setup</a>`;
  element.replaceWith(note);
}

function applyConfig(config) {
  // What this server cannot do (the online demo has no API keys) is not shown at all, only a note.
  state.config = config;
  if (!config.live) {
    offNote(document.querySelector(".dropzone"), "Your own photos", true);
    offNote($("repair-again"), "Repair");
  }
  if (!config.voice) {
    offNote($("voice-card"), "Voice editing");
    offNote($("adapter-textbox"), "Free text, voice and Spark Open outlines", true);
  } else if (!config.speech) {  // typing works; speaking also needs MODEL_API_KEY
    $("voice-mic").remove();
    $("adapter-mic").remove();
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
  const { runs } = await getJSON("/api/runs");
  const examples = runs.filter((name) => !name.startsWith("live-"));
  $("example-list").innerHTML = examples.map((n) => `<button data-run="${n}">${n}</button>`).join("");
  document.querySelectorAll("#example-list button").forEach((b) => b.addEventListener("click", () => chooseRun(b.dataset.run)));

  // Deep link for screenshots and recordings: ?run=A_light&step=search
  const params = new URLSearchParams(location.search);
  const run = params.get("run");
  if (run && runs.includes(run)) await openDeepLink(run, params);
  document.body.dataset.ready = "true";  // webapp/screenshot.py waits for this
})();

async function openDeepLink(run, params) {
  const step = params.get("step") || "capture";
  state.round = params.get("round");  // an older saved round, for the search screen only
  await chooseRun(run);
  if (step === "capture") return;
  await measure();
  if (step === "measure") return;
  await streamCandidates();
  if (step !== "edit" && step !== "export") return;
  await showModel();
  if (params.get("match")) await showMatching(params.get("match"));
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
