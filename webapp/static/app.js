// ReverseCAD front end in replay mode (saved runs, no API calls).
// Screen 1: choose a saved run, click the part, enter the thickness.
// Screen 2: card, part outline and holes drawn over the photo, measurement table beside it.
// Screen 3: candidates arrive one by one (server-sent events) into a grid with score and reasons.
// Screen 4: the result in 3D (three.js); a slider per named parameter rebuilds the part on release.
import { createViewer } from "./viewer.js";

const state = { run: null, live: false, image: null, click: null, analysis: null, stream: null, viewer: null,
                winner: null };
const canvas = document.getElementById("photo-canvas");
const context = canvas.getContext("2d");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function showStep(step) {
  document.querySelectorAll("#steps li").forEach((li) => li.classList.toggle("active", li.dataset.step === String(step)));
  [1, 2, 3, 4, 5].forEach((n) => document.getElementById(`screen-${n}`).classList.toggle("hidden", step !== n));
  // The stage shows the photo for screens 1-2, the candidate grid for 3 and the 3D view for 4-5.
  canvas.classList.toggle("hidden", step >= 3);
  document.getElementById("candidate-grid").classList.toggle("hidden", step !== 3);
  document.getElementById("viewer").classList.toggle("hidden", step < 4);
}

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

// ---------- drawing ----------
function drawPolygon(points, color, closed = true) {
  context.beginPath();
  points.forEach(([x, y], i) => (i ? context.lineTo(x, y) : context.moveTo(x, y)));
  if (closed) context.closePath();
  context.strokeStyle = color;
  context.lineWidth = Number(css("--overlay-line-width")) * (canvas.width / canvas.clientWidth);
  context.stroke();
}

function drawLabel(text, x, y) {
  const scale = canvas.width / canvas.clientWidth;
  context.font = `${14 * scale}px ${css("--font-mono")}`;
  const width = context.measureText(text).width;
  context.fillStyle = css("--color-overlay-label-bg");
  context.fillRect(x - 4 * scale, y - 16 * scale, width + 8 * scale, 22 * scale);
  context.fillStyle = css("--color-overlay-label-text");
  context.fillText(text, x, y);
}

function drawClick() {
  if (!state.click) return;
  const [x, y] = state.click;
  const size = 14 * (canvas.width / canvas.clientWidth);
  drawPolygon([[x - size, y], [x + size, y]], css("--color-overlay-click"), false);
  drawPolygon([[x, y - size], [x, y + size]], css("--color-overlay-click"), false);
}

function render() {
  if (!state.image) return;
  canvas.width = state.image.naturalWidth;
  canvas.height = state.image.naturalHeight;
  context.drawImage(state.image, 0, 0);
  const a = state.analysis;
  if (a) {
    drawPolygon(a.card_corners_px, css("--color-overlay-card"));
    drawPolygon(a.outline_px, css("--color-overlay-part"));
    a.holes.forEach((hole) => {
      drawPolygon(hole.contour_px, css("--color-overlay-hole"));
      drawLabel(hole.label, hole.center_px[0] + 12, hole.center_px[1] - 12);
    });
    const xs = a.outline_px.map((p) => p[0]);
    const ys = a.outline_px.map((p) => p[1]);
    drawLabel(`${a.outline_mm.length} × ${a.outline_mm.width} mm`, Math.min(...xs), Math.min(...ys) - 12);
  }
  drawClick();
}

// ---------- screen 1 ----------
function setLive(live) {
  state.live = live;
  document.querySelectorAll(".live-only").forEach((element) => element.classList.toggle("hidden", !live));
}

async function chooseRun(name) {
  setLive(false);
  state.run = name;
  state.analysis = null;
  state.image = await loadImage(`/api/runs/${name}/photo`);
  // The saved run's click is shown until the user clicks somewhere else.
  const saved = await getJSON(`/api/runs/${name}/info`);
  state.click = saved.click_px;
  render();
  document.getElementById("analyze").disabled = false;
}

canvas.addEventListener("click", (event) => {
  if (!state.image) return;
  const box = canvas.getBoundingClientRect();
  state.click = [
    Math.round((event.clientX - box.left) * (canvas.width / box.width)),
    Math.round((event.clientY - box.top) * (canvas.height / box.height)),
  ];
  render();
  document.getElementById("analyze").disabled = false;
});

document.getElementById("run-select").addEventListener("change", (event) => chooseRun(event.target.value));

document.getElementById("photo-upload").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const form = new FormData();
  form.append("photo", file);
  const response = await fetch("/api/live/upload", { method: "POST", body: form });
  if (!response.ok) {
    alert(`Upload failed: ${(await response.json()).detail}`);
    return;
  }
  const { name } = await response.json();
  setLive(true);
  state.run = name;
  state.analysis = null;
  state.click = null;  // live: the user must click the part
  state.image = await loadImage(`/api/runs/${name}/photo`);
  render();
  document.getElementById("analyze").disabled = true;
});

// ---------- screen 2 ----------
function fillTable(a) {
  const rows = [
    ["Outline", `${a.table.outline.length_mm} × ${a.table.outline.width_mm} mm`],
    ["Corners", a.table.outline.vertex_count],
    ["Holes", a.table.hole_count],
    ...a.table.holes.map((h, i) => {
      const size = h.shape === "circle" ? `Ø ${h.diameter_mm}` : `${h.length_mm} × ${h.width_mm}`;
      const [u, v] = h.center_from_part_center_mm;
      return [`Hole ${i + 1} (${h.shape})`, `${size} mm at [${u}, ${v}]`];
    }),
    ["Thickness (entered)", `${document.getElementById("thickness").value} mm`],
  ];
  document.getElementById("measure-table").innerHTML = rows
    .map(([name, value]) => `<tr><td>${name}</td><td class="number">${value}</td></tr>`)
    .join("");
  document.getElementById("measure-summary").textContent =
    `Part found by ${a.part_found_by}; ${a.scale_used} scale (card edges ${a.card_edge_differences_pct.join(" / ")} %); ` +
    `holes by ${a.hole_method}.`;
}

function showAnalysis(analysis) {
  state.analysis = analysis;
  fillTable(analysis);
  render();
}

function measureLive() {
  // Progress messages while SAM runs (decoding its masks takes seconds), then the overlay.
  const summary = document.getElementById("measure-summary");
  document.getElementById("measure-table").innerHTML = "";
  document.getElementById("to-candidates").disabled = true;
  const [x, y] = state.click;
  const stream = new EventSource(`/api/live/${state.run}/measure/stream?x=${x}&y=${y}`);
  stream.addEventListener("progress", (message) => (summary.textContent = JSON.parse(message.data).message));
  stream.addEventListener("analysis", (message) => {
    stream.close();
    showAnalysis(JSON.parse(message.data));
    document.getElementById("to-candidates").disabled = false;
  });
  stream.addEventListener("error", (message) => {
    stream.close();
    summary.textContent = message.data ? `Failed: ${JSON.parse(message.data).message}` : "The connection was lost.";
  });
}

document.getElementById("analyze").addEventListener("click", async () => {
  showStep(2);
  if (state.live) {
    measureLive();
  } else {
    showAnalysis(await getJSON(`/api/runs/${state.run}/analysis`));
    document.getElementById("to-candidates").disabled = false;
  }
});

document.getElementById("back-to-1").addEventListener("click", () => {
  state.analysis = null;
  render();
  showStep(1);
});

// ---------- screen 3 ----------
function candidateCard(event) {
  const card = document.createElement("div");
  card.className = `candidate-card ${event.status}`;
  card.id = `candidate-${event.candidate}`;
  const picture = event.silhouette
    ? `<img src="${event.silhouette}" alt="candidate ${event.candidate} silhouette">`
    : `<div class="placeholder">no shape</div>`;
  const score = event.iou == null ? "" : `IoU ${event.iou.toFixed(4)} · ${event.parameters} parameters`;
  const reasons = event.reasons.length ? `<ul>${event.reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : "";
  card.innerHTML = `${picture}<strong>Candidate ${event.candidate}: ${event.status}</strong><span>${score}</span>${reasons}`;
  return card;
}

function streamCandidates() {
  if (state.stream) state.stream.close();
  const grid = document.getElementById("candidate-grid");
  const progress = document.getElementById("candidate-progress");
  const result = document.getElementById("candidate-result");
  grid.innerHTML = "";
  result.textContent = "";
  document.getElementById("to-model").disabled = true;
  let received = 0;
  const thickness = document.getElementById("thickness").value;
  const count = document.getElementById("candidate-count").value;
  state.stream = new EventSource(state.live
    ? `/api/live/${state.run}/candidates/stream?count=${count}&thickness=${thickness}`
    : `/api/runs/${state.run}/candidates/stream`);
  state.stream.addEventListener("progress", (message) => (progress.textContent = JSON.parse(message.data).message));
  state.stream.addEventListener("candidate", (message) => {
    grid.appendChild(candidateCard(JSON.parse(message.data)));
    progress.textContent = `${++received} candidates received…`;
  });
  state.stream.addEventListener("done", (message) => {
    state.stream.close();
    const done = JSON.parse(message.data);
    progress.textContent = `${done.compiled} of ${done.candidate_count} candidates compiled (round ${done.round}).`;
    if (done.winner) {
      document.getElementById(`candidate-${done.winner}`)?.classList.add("winner");
      result.textContent = `Winner: candidate ${done.winner}.`;
    } else {
      result.textContent = `No candidate passed: ${done.result_source}.`;
    }
    document.getElementById("to-model").disabled = !done.result_source || done.result_source.startsWith("none");
  });
  state.stream.addEventListener("error", (message) => {
    // A server 'error' event carries a message; a lost connection does not.
    progress.textContent = message.data ? `Failed: ${JSON.parse(message.data).message}`
      : "The candidate stream stopped unexpectedly.";
    state.stream.close();
  });
}

document.getElementById("to-candidates").addEventListener("click", () => {
  showStep(3);
  streamCandidates();
});

document.getElementById("back-to-2").addEventListener("click", () => {
  if (state.stream) state.stream.close();
  showStep(2);
});

// ---------- screen 4 ----------
function currentValues() {
  const values = {};
  document.querySelectorAll("#sliders input").forEach((input) => (values[input.name] = Number(input.value)));
  return values;
}

async function rebuild() {
  const status = document.getElementById("model-status");
  status.textContent = "Building…";
  const started = performance.now();
  const response = await fetch(`/api/runs/${state.run}/model`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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
  const range = Number(css("--slider-range"));
  const value = parameter.default;
  const span = Math.max(Math.abs(value) * range, 1);  // at least ±1 for zero or tiny defaults
  const row = document.createElement("label");
  row.className = "slider";
  row.innerHTML = `<span>${parameter.name}</span><output>${value}</output>
    <input type="range" name="${parameter.name}" min="${value - span}" max="${value + span}" step="0.1" value="${value}">`;
  const input = row.querySelector("input");
  input.dataset.default = value;
  input.addEventListener("input", () => (row.querySelector("output").textContent = input.value));
  input.addEventListener("change", rebuild);  // on release, not while dragging
  return row;
}

async function showModel() {
  showStep(4);
  if (!state.viewer) state.viewer = createViewer(document.getElementById("viewer"));
  state.viewer.resize();
  state.viewer.reset();
  state.winner = await getJSON(`/api/runs/${state.run}/winner`);
  document.getElementById("model-source").textContent =
    `${state.winner.program} (${state.winner.source}), ${state.winner.parameters.length} parameters.`;
  const sliders = document.getElementById("sliders");
  sliders.innerHTML = "";
  state.winner.parameters.forEach((p) => sliders.appendChild(slider(p)));
  await rebuild();
}

// ---------- screen 5 ----------
async function downloadFile(format) {
  const status = document.getElementById("download-status");
  status.textContent = `Preparing ${format.toUpperCase()}…`;
  const response = await fetch(`/api/runs/${state.run}/download?format=${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
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

function showDownload() {
  showStep(5);
  document.getElementById("download-values").innerHTML = Object.entries(currentValues())
    .map(([name, value]) => `<tr><td>${name}</td><td class="number">${value}</td></tr>`)
    .join("");
  document.getElementById("download-status").textContent = "";
}

document.querySelectorAll("#screen-5 button[data-format]").forEach((button) =>
  button.addEventListener("click", () => downloadFile(button.dataset.format)));
document.getElementById("to-download").addEventListener("click", showDownload);
document.getElementById("back-to-4").addEventListener("click", () => showStep(4));

document.getElementById("to-model").addEventListener("click", showModel);
document.getElementById("back-to-3").addEventListener("click", () => showStep(3));
document.getElementById("reset-parameters").addEventListener("click", () => {
  document.querySelectorAll("#sliders input").forEach((input) => {
    input.value = input.dataset.default;
    input.closest(".slider").querySelector("output").textContent = input.value;
  });
  rebuild();
});

// ---------- start ----------
(async () => {
  showStep(1);
  const { runs } = await getJSON("/api/runs");
  const select = document.getElementById("run-select");
  select.innerHTML = runs.map((name) => `<option value="${name}">${name}</option>`).join("");
  const initial = runs.includes("A_light") ? "A_light" : runs[0];
  if (initial) {
    select.value = initial;
    await chooseRun(initial);
  }
})();
