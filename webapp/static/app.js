// ReverseCAD front end. Three screens (layout adapted from the Stitch screens in design/):
//   Capture: upload a photo or try an example, click the part, set the thickness, measure.
//   Search:  candidates arrive one by one (server-sent events) into a grid; the selected one grows to 2×2.
//   Edit:    the result in 3D with dimension labels, a slider per named parameter, and downloads.
// Every number shown comes from the back end or from the built model; nothing is made up for display.
// ?run=<name>&step=capture|measure|search|edit opens a saved run on that screen (screenshots, videos);
// with step=edit, &set=<parameter>:<value>,... also moves sliders.
import { createViewer } from "./viewer.js";

const state = {
  screen: "capture", run: null, live: false, image: null, click: null, analysis: null,
  stream: null, viewer: null, winner: null, done: null, seen: [], expected: null,
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
  ["capture", "search", "edit"].forEach((name) => $(`screen-${name}`).classList.toggle("hidden", name !== screen));
  if (screen === "capture") render();
  if (screen === "edit" && state.viewer) state.viewer.resize();
  updateHeader();
}

function enableSteps() {
  const canEdit = !!(state.done && state.done.result_source && !state.done.result_source.startsWith("none"));
  document.querySelectorAll('[data-screen="search"]').forEach((b) => (b.disabled = !state.analysis));
  document.querySelectorAll('[data-screen="edit"]').forEach((b) => (b.disabled = !canEdit));
}

document.querySelectorAll("#steps button, #rail button").forEach((button) =>
  button.addEventListener("click", () => {
    if (button.dataset.screen === "edit" && !state.winner) showModel();
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
  const count = state.seen.length;
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
  state.done = null;
  state.winner = null;
  $("measure-results").classList.add("hidden");
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
    const rows = Math.ceil(cells / columns);
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
  $("pick-name").textContent = chosen ? `#${pad2(chosen.candidate)}` : state.done ? state.done.result_source || "no result" : "–";
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
        streamItem("OK", "tag-ok", `candidate ${idOf(event)} passed: IoU ${event.iou.toFixed(4)}${fit}`);
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
        streamItem("FALLBACK", "tag-bad", `no candidate passed: ${state.done.result_source}`);
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

// ---------- edit ----------
const LABEL_FOR = [[/diam|hole|bore/, "hole"], [/thick|height|depth/, "thickness"], [/width/, "width"], [/length/, "length"]];
const labelKey = (name) => (LABEL_FOR.find(([pattern]) => pattern.test(name.toLowerCase())) || [])[1];
const prettyName = (name) => name.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const unitFor = (name) => (/count|number|^n_/.test(name) ? "" : /angle/.test(name) ? "°" : " mm");

function currentValues() {
  const values = {};
  document.querySelectorAll("#sliders input").forEach((input) => (values[input.name] = Number(input.value)));
  return values;
}

function changedLabels() {
  return [...document.querySelectorAll("#sliders .slider.changed input")].map((i) => labelKey(i.name)).filter(Boolean);
}

async function rebuild() {
  const status = $("model-status");
  status.textContent = "Building…";
  const started = performance.now();
  const response = await fetch(`/api/runs/${state.run}/model`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parameters: currentValues() }),
  });
  if (!response.ok) {
    status.textContent = `Not built: ${(await response.json()).detail}`;
    return;
  }
  const features = JSON.parse(response.headers.get("X-Model-Features") || "null");
  state.viewer.show(await response.arrayBuffer(), features);
  state.viewer.setChanged(changedLabels());
  if (features) {
    const [x0, y0, z0, x1, y1, z1] = features.box;
    $("model-size").innerHTML = `<strong>${(x1 - x0).toFixed(2)} × ${(y1 - y0).toFixed(2)} × ${(z1 - z0).toFixed(2)} mm</strong>`
      + ` · ${features.holes.length} round holes`;
  }
  status.textContent = `Built in ${((performance.now() - started) / 1000).toFixed(1)} s`;
}

function slider(parameter) {
  const value = parameter.default;
  const span = Math.max(Math.abs(value) * Number(css("--slider-range")), 1);
  const unit = unitFor(parameter.name);
  const row = document.createElement("label");
  row.className = "slider";
  // A step of 0.01 keeps the program's own value exact (with 0.1 the browser snapped 40.26 to 40.3).
  const min = (value - span).toFixed(2);
  const max = (value + span).toFixed(2);
  row.innerHTML = `<span class="slider-head"><span class="name">${prettyName(parameter.name)}</span><output>${value}${unit}</output></span>
    <input type="range" name="${parameter.name}" min="${min}" max="${max}" step="0.01" value="${value}">
    <span class="range"><span>${min}</span><span class="default">PROGRAM: ${value}</span><span>${max}</span></span>`;
  const input = row.querySelector("input");
  input.dataset.default = value;
  input.addEventListener("input", () => {
    row.querySelector("output").textContent = `${input.value}${unit}`;
    row.classList.toggle("changed", Number(input.value) !== Number(input.dataset.default));
    state.viewer.setChanged(changedLabels());
  });
  input.addEventListener("change", rebuild);
  return row;
}

async function showModel() {
  setScreen("edit");
  if (!state.viewer) state.viewer = createViewer($("viewer"), { shiftRight: 140 });  // clear of the capture-fit inset
  state.viewer.resize();
  state.viewer.reset();
  state.winner = await getJSON(`/api/runs/${state.run}/winner`);
  const w = state.winner;
  $("model-program").textContent = `Program ${w.program}`;
  $("model-source").textContent = `Source: ${w.source}`;
  $("fit-image").src = `/api/runs/${state.run}/capture-fit.png`;
  $("fit-iou").textContent = w.iou == null ? "" : `IoU ${w.iou.toFixed(4)}`;
  // The program's own values (before any slider moves) against the measurements and, if known, the truth.
  $("fit-table").innerHTML = tableHTML(resultRows({ fit_mm: w.fit_mm, ground_truth: w.ground_truth }));
  const sliders = $("sliders");
  sliders.innerHTML = "";
  w.parameters.forEach((p) => sliders.appendChild(slider(p)));
  await rebuild();
  await showCompletion();
}
$("to-model").addEventListener("click", showModel);

async function showCompletion() {
  // The "possible break" card: shown when Muse Wonder suggested a completion and it was not ignored.
  const data = await getJSON(`/api/runs/${state.run}/completion`);
  const c = data.available ? data : null;
  state.completion = c;
  state.viewer.showSuggestion(null);
  const hidden = !c || c.broken === false || c.decision === "ignore";
  $("break-card").classList.toggle("hidden", hidden);
  if (hidden) return;
  const applied = c.decision === "apply";
  const check = c.check || {};
  $("break-suggestion").textContent = c.suggestion || "";
  $("break-rationale").textContent = c.rationale || "";
  $("break-note").textContent = !c.valid ? `Not offered: ${(check.reasons || ["no program returned"]).join("; ")}`
    : applied ? "Applied: the parameters above belong to the completed program."
    : [check.added_volume_mm3 > 0 ? `adds ${check.added_volume_mm3.toFixed(0)} mm³ (orange in the 3D view)` : "",
       check.removed_volume_mm3 > 0 ? `cuts ${check.removed_volume_mm3.toFixed(0)} mm³` : ""].filter(Boolean).join(", ");
  $("break-apply").disabled = !c.valid;
  $("break-apply").innerHTML = applied ? "Undo" : `<span class="icon">check</span>Apply`;
  $("break-ignore").classList.toggle("hidden", applied);
  if (!applied && c.valid && c.added_stl) state.viewer.showSuggestion(await (await fetch(c.added_stl)).arrayBuffer());
}

$("break-apply").addEventListener("click", async () => {
  await fetch(`/api/runs/${state.run}/completion/${state.completion.decision === "apply" ? "undo" : "apply"}`, { method: "POST" });
  await showModel();  // the result program changed: new parameters, new model
});
$("break-ignore").addEventListener("click", async () => {
  await fetch(`/api/runs/${state.run}/completion/ignore`, { method: "POST" });
  await showCompletion();
});

$("reset-parameters").addEventListener("click", () => {
  document.querySelectorAll("#sliders .slider").forEach((row) => {
    const input = row.querySelector("input");
    input.value = input.dataset.default;
    row.querySelector("output").textContent = `${input.value}${unitFor(input.name)}`;
    row.classList.remove("changed");
  });
  rebuild();
});

document.querySelectorAll(".view-tools button").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.view !== "fit") document.querySelectorAll(".view-tools button").forEach((o) => o.classList.toggle("active", o === b));
  state.viewer?.setView(b.dataset.view);
}));

async function downloadFile(format) {
  const status = $("download-status");
  status.textContent = `Preparing ${format.toUpperCase()}…`;
  const response = await fetch(`/api/runs/${state.run}/download?format=${format}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ parameters: currentValues() }),
  });
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

// ---------- start ----------
(async () => {
  setScreen("capture");
  updateProcedure();
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
  if (step !== "edit") return;
  await showModel();
  // &set=length:95,hole_diameter:7 moves sliders as a user would (to show a changed state).
  const changes = (params.get("set") || "").split(",").filter(Boolean).map((pair) => pair.split(":"));
  for (const [name, value] of changes) {
    const input = document.querySelector(`#sliders input[name="${name}"]`);
    if (!input) continue;
    input.value = value;
    input.dispatchEvent(new Event("input"));
  }
  if (changes.length) await rebuild();
}
