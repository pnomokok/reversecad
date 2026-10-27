// ReverseCAD front end. Three screens:
//   Capture: upload a photo or try an example, click the part, set the thickness, measure.
//   Search:  candidates arrive one by one (server-sent events) with silhouette, score and reasons.
//   Edit:    the result in 3D with a slider per named parameter, and downloads.
// Every number shown comes from the back end; nothing is made up for display.
// ?run=<name>&step=capture|measure|search|edit opens a saved run on that screen (screenshots, videos);
// with step=edit, &set=<parameter>:<value>,... also moves sliders.
import { createViewer } from "./viewer.js";

const state = {
  screen: "capture", run: null, live: false, image: null, click: null, analysis: null,
  stream: null, viewer: null, winner: null, done: null,
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

// ---------- screens ----------
function setScreen(screen) {
  state.screen = screen;
  document.querySelectorAll("#steps button").forEach((b) => b.classList.toggle("active", b.dataset.screen === screen));
  ["capture", "search", "edit"].forEach((name) => $(`panel-${name}`).classList.toggle("hidden", name !== screen));
  $("stage-empty").classList.toggle("hidden", !(screen === "capture" && !state.image));
  canvas.classList.toggle("hidden", !(screen === "capture" && state.image));
  $("candidate-grid").classList.toggle("hidden", screen !== "search");
  $("viewer").classList.toggle("hidden", screen !== "edit");
  updateStageBar();
}

function enableSteps() {
  document.querySelector('#steps [data-screen="search"]').disabled = !state.analysis;
  document.querySelector('#steps [data-screen="edit"]').disabled = !(state.done && state.done.result_source
    && !state.done.result_source.startsWith("none"));
}

document.querySelectorAll("#steps button").forEach((button) =>
  button.addEventListener("click", () => {
    if (button.dataset.screen === "edit" && !state.winner) showModel();
    else setScreen(button.dataset.screen);
  }));

function stageBar(items) {
  // items: [label, value] pairs; values are always computed by the back end
  $("stage-bar").innerHTML = items.map(([label, value]) => `<span>${label} <strong>${value}</strong></span>`).join("");
}

function updateStageBar() {
  const a = state.analysis;
  if (state.screen === "capture" && a) {
    stageBar([["Scale", a.scale_used], ["Card", `${a.card_mm_per_pixel} mm/px`],
              ["Card edges", `${a.card_edge_differences_pct.join(" / ")} %`], ["Part found by", a.part_found_by],
              ["Holes by", a.hole_method]]);
  } else if (state.screen === "search" && state.done) {
    stageBar([["Round", state.done.round], ["Compiled", `${state.done.compiled} / ${state.done.candidate_count}`],
              ["Result", state.done.winner ? `candidate ${state.done.winner}` : state.done.result_source]]);
  } else if (state.screen === "edit" && state.winner) {
    stageBar([["Program", state.winner.program], ["Source", state.winner.source],
              ["Parameters", state.winner.parameters.length]]);
  } else {
    stageBar([]);
  }
  $("topbar-status").textContent = state.run ? `${state.live ? "Live" : "Example"} · ${state.run}` : "";
}

// ---------- capture: photo and overlay ----------
function scale() {
  return canvas.width / (canvas.clientWidth || canvas.width);
}

function polygon(points, color, width, closed = true) {
  context.beginPath();
  points.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
  if (closed) context.closePath();
  context.strokeStyle = color;
  context.lineWidth = width * scale();
  context.stroke();
}

function callout(text, x, y) {
  // A dimension box: dark fill, white border, white monospace text, centered on (x, y).
  const s = scale();
  context.font = `700 ${Number(css("--callout-font-px")) * s}px ${css("--font-mono")}`;
  const width = context.measureText(text).width + 16 * s;
  const height = Number(css("--callout-font-px")) * 1.6 * s;
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
  const vertical = Math.abs(x2 - x1) < Math.abs(y2 - y1);
  context.strokeStyle = css("--color-dimension");
  context.lineWidth = 2 * s;
  context.beginPath();
  context.moveTo(x1, y1);
  context.lineTo(x2, y2);
  for (const [x, y] of [[x1, y1], [x2, y2]]) {  // end ticks across the line
    if (vertical) { context.moveTo(x - tick, y); context.lineTo(x + tick, y); }
    else { context.moveTo(x, y - tick); context.lineTo(x, y + tick); }
  }
  context.stroke();
}

function drawMeasurements(a) {
  const s = scale();
  polygon(a.card_corners_px, css("--color-overlay-card"), 2);
  polygon(a.outline_px, css("--color-overlay-part"), Number(css("--overlay-line-width")));
  a.holes.forEach((hole) => polygon(hole.contour_px, css("--color-overlay-hole"), 2));

  const xs = a.outline_px.map((p) => p[0]);
  const ys = a.outline_px.map((p) => p[1]);
  const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const center = [(left + right) / 2, (top + bottom) / 2];

  // Holes: a box moved from each hole toward the part's center, so it stays clear of the outer dimensions.
  a.holes.forEach((hole) => {
    const [hx, hy] = hole.center_px;
    const [dx, dy] = [center[0] - hx, center[1] - hy];
    const length = Math.hypot(dx, dy) || 1;
    const shift = Math.min(70 * s, length * 0.6);
    callout(hole.size, hx + (dx / length) * shift, hy + (dy / length) * shift);
  });

  // Outline last, so its boxes stay on top: length along the longer side of the part's box.
  const horizontalIsLength = right - left >= bottom - top;
  const [horizontal, vertical] = horizontalIsLength
    ? [a.outline_mm.length, a.outline_mm.width] : [a.outline_mm.width, a.outline_mm.length];
  const gap = 56 * s;
  const room = 130 * s;  // space a dimension box needs outside the part
  const y = top - gap > room / 2 ? top - gap : bottom + gap;  // above the part, or below if no room
  const x = canvas.width - (right + gap) > room ? right + gap : left - gap;  // right of it, or left
  dimensionLine(left, y, right, y);
  callout(`${horizontal.toFixed(2)} mm`, center[0], y);
  dimensionLine(x, top, x, bottom);
  callout(`${vertical.toFixed(2)} mm`, x, center[1]);
}

function drawClick() {
  if (!state.click) return;
  const [x, y] = state.click;
  const size = 16 * scale();
  polygon([[x - size, y], [x + size, y]], css("--color-overlay-click"), 3, false);
  polygon([[x, y - size], [x, y + size]], css("--color-overlay-click"), 3, false);
}

function render() {
  if (!state.image) return;
  canvas.width = state.image.naturalWidth;
  canvas.height = state.image.naturalHeight;
  context.drawImage(state.image, 0, 0);
  if (state.analysis) drawMeasurements(state.analysis);
  drawClick();
}
window.addEventListener("resize", render);

function thickness() {
  const value = Number(String($("thickness").value).replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function updateProcedure() {
  // Ticked when true: the card counts as found once the measurement has used it.
  const done = { card: !!state.analysis, click: !!state.click, thickness: thickness() !== null };
  for (const key of ["card", "click", "thickness"]) $(`step-${key}`).classList.toggle("done", done[key]);
}

function resetResults() {
  state.analysis = null;
  state.done = null;
  state.winner = null;
  $("measure-results").classList.add("hidden");
  $("to-candidates").classList.add("hidden");
  $("capture-status").textContent = "";
  enableSteps();
  updateProcedure();
}

function setLive(live) {
  state.live = live;
  document.querySelectorAll(".live-only").forEach((element) => element.classList.toggle("hidden", !live));
}

async function chooseRun(name) {
  setLive(false);
  state.run = name;
  resetResults();
  document.querySelectorAll("#example-list button").forEach((b) => b.classList.toggle("active", b.dataset.run === name));
  state.image = await loadImage(`/api/runs/${name}/photo`);
  state.click = (await getJSON(`/api/runs/${name}/info`)).click_px;  // the example's own click
  setScreen("capture");
  render();
  updateProcedure();
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
  setScreen("capture");
  render();
  updateProcedure();
  $("analyze").disabled = true;
  $("capture-status").textContent = "Click the part in the photo (not a hole).";
});

canvas.addEventListener("click", (event) => {
  if (!state.image) return;
  const box = canvas.getBoundingClientRect();
  state.click = [Math.round((event.clientX - box.left) * (canvas.width / box.width)),
                 Math.round((event.clientY - box.top) * (canvas.height / box.height))];
  render();
  updateProcedure();
  $("analyze").disabled = false;
});

function stepThickness(delta) {
  $("thickness").value = Math.max(0.5, (thickness() ?? 3) + delta).toFixed(1);
  updateProcedure();
}
$("thickness-down").addEventListener("click", () => stepThickness(-0.5));
$("thickness-up").addEventListener("click", () => stepThickness(0.5));
$("thickness").addEventListener("input", updateProcedure);

function showAnalysis(a) {
  state.analysis = a;
  const holes = a.holes.map((h, i) => [`Hole ${i + 1}`, `${h.shape} ${h.size}`]);
  const rows = [["Outline", `${a.outline_mm.length.toFixed(2)} × ${a.outline_mm.width.toFixed(2)} mm`],
                ["Corners", a.outline_mm.corners], ["Holes", a.holes.length], ...holes];
  $("measure-table").innerHTML = rows.map(([k, v]) => `<tr><td>${k}</td><td class="number">${v}</td></tr>`).join("");
  $("measure-results").classList.remove("hidden");
  $("to-candidates").classList.remove("hidden");
  render();
  updateProcedure();
  enableSteps();
  updateStageBar();
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
  if (state.live) await measureLive();
  else showAnalysis(await getJSON(`/api/runs/${state.run}/analysis`));
  $("analyze").disabled = false;
}
$("analyze").addEventListener("click", measure);

// ---------- search ----------
function candidateCard(event) {
  const card = document.createElement("div");
  card.className = `candidate-card ${event.status}`;
  card.id = `candidate-${event.candidate}`;
  const picture = event.silhouette
    ? `<img src="${event.silhouette}" alt="candidate ${event.candidate} silhouette">`
    : `<div class="placeholder">no shape</div>`;
  const score = event.iou == null ? "" : `IoU ${event.iou.toFixed(4)} · ${event.parameters} params`;
  const reasons = event.reasons.length ? `<ul>${event.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : "";
  card.innerHTML = `<header><span>#${String(event.candidate).padStart(2, "0")}</span>`
    + `<span class="status">${event.status.toUpperCase()}</span></header>${picture}<span class="score">${score}</span>${reasons}`;
  return card;
}

function streamCandidates() {
  return new Promise((resolve) => {
    if (state.stream) state.stream.close();
    setScreen("search");
    const grid = $("candidate-grid");
    grid.innerHTML = "";
    state.done = null;
    state.winner = null;
    enableSteps();
    $("to-model").disabled = true;
    $("search-best").innerHTML = "";
    const seen = [];
    const update = () => {
      const passed = seen.filter((e) => e.status === "passed");
      $("search-count").textContent = seen.length;
      $("search-split").textContent = `${passed.length} passed · ${seen.length - passed.length} rejected or failed`;
      const best = passed.reduce((a, b) => (a && a.iou >= b.iou ? a : b), null);
      $("search-best").innerHTML = best
        ? `<tr><td>Candidate</td><td class="number">#${best.candidate}</td></tr>`
          + `<tr><td>IoU</td><td class="number">${best.iou.toFixed(4)}</td></tr>`
          + `<tr><td>Parameters</td><td class="number">${best.parameters}</td></tr>` : "";
    };
    const count = $("candidate-count").value;
    state.stream = new EventSource(state.live
      ? `/api/live/${state.run}/candidates/stream?count=${count}&thickness=${thickness() ?? 3}`
      : `/api/runs/${state.run}/candidates/stream`);
    state.stream.addEventListener("progress", (m) => ($("search-progress").textContent = JSON.parse(m.data).message));
    state.stream.addEventListener("candidate", (m) => {
      const event = JSON.parse(m.data);
      seen.push(event);
      grid.appendChild(candidateCard(event));
      update();
    });
    state.stream.addEventListener("done", (m) => {
      state.stream.close();
      state.done = JSON.parse(m.data);
      if (state.done.winner) $(`candidate-${state.done.winner}`)?.classList.add("winner");
      $("search-progress").textContent = state.done.winner
        ? `Selected: candidate ${state.done.winner}.` : `No candidate passed: ${state.done.result_source}.`;
      $("to-model").disabled = !state.done.result_source || state.done.result_source.startsWith("none");
      enableSteps();
      updateStageBar();
      resolve();
    });
    state.stream.addEventListener("error", (m) => {
      state.stream.close();
      $("search-progress").textContent = m.data ? `Failed: ${JSON.parse(m.data).message}`
        : "The candidate stream stopped unexpectedly.";
      resolve();
    });
  });
}
$("to-candidates").addEventListener("click", streamCandidates);

// ---------- edit ----------
function currentValues() {
  const values = {};
  document.querySelectorAll("#sliders input").forEach((input) => (values[input.name] = Number(input.value)));
  return values;
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
  state.viewer.show(await response.arrayBuffer());
  status.textContent = `Built in ${((performance.now() - started) / 1000).toFixed(1)} s.`;
}

function slider(parameter) {
  const value = parameter.default;
  const span = Math.max(Math.abs(value) * Number(css("--slider-range")), 1);
  const row = document.createElement("label");
  row.className = "slider";
  const min = (value - span).toFixed(1);
  const max = (value + span).toFixed(1);
  row.innerHTML = `<span class="name">${parameter.name}</span><output>${value}</output>
    <input type="range" name="${parameter.name}" min="${min}" max="${max}" step="0.1" value="${value}">
    <span class="range"><span>${min}</span><span>default ${value}</span><span>${max}</span></span>`;
  const input = row.querySelector("input");
  input.dataset.default = value;
  input.addEventListener("input", () => {
    row.querySelector("output").textContent = input.value;
    row.classList.toggle("changed", Number(input.value) !== Number(input.dataset.default));
  });
  input.addEventListener("change", rebuild);
  return row;
}

async function showModel() {
  setScreen("edit");
  if (!state.viewer) state.viewer = createViewer($("viewer"));
  state.viewer.resize();
  state.viewer.reset();
  state.winner = await getJSON(`/api/runs/${state.run}/winner`);
  $("model-source").textContent = `${state.winner.program} · ${state.winner.source}`;
  const sliders = $("sliders");
  sliders.innerHTML = "";
  state.winner.parameters.forEach((p) => sliders.appendChild(slider(p)));
  updateStageBar();
  await rebuild();
}
$("to-model").addEventListener("click", showModel);

$("reset-parameters").addEventListener("click", () => {
  document.querySelectorAll("#sliders .slider").forEach((row) => {
    const input = row.querySelector("input");
    input.value = input.dataset.default;
    row.querySelector("output").textContent = input.value;
    row.classList.remove("changed");
  });
  rebuild();
});

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
  if (!run || !runs.includes(run)) return;
  const step = params.get("step") || "capture";
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
})();
