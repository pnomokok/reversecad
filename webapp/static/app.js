// ReverseCAD front end in replay mode (saved runs, no API calls).
// Screen 1: choose a saved run, click the part, enter the thickness.
// Screen 2: card, part outline and holes drawn over the photo, measurement table beside it.
// Screen 3: candidates arrive one by one (server-sent events) into a grid with score and reasons.

const state = { run: null, image: null, click: null, analysis: null, stream: null };
const canvas = document.getElementById("photo-canvas");
const context = canvas.getContext("2d");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function showStep(step) {
  document.querySelectorAll("#steps li").forEach((li) => li.classList.toggle("active", li.dataset.step === String(step)));
  [1, 2, 3].forEach((n) => document.getElementById(`screen-${n}`).classList.toggle("hidden", step !== n));
  // The stage shows the photo for screens 1-2 and the candidate grid for screen 3.
  canvas.classList.toggle("hidden", step === 3);
  document.getElementById("candidate-grid").classList.toggle("hidden", step !== 3);
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
async function chooseRun(name) {
  state.run = name;
  state.analysis = null;
  state.image = await loadImage(`/api/runs/${name}/photo`);
  // The saved run's click is shown until the user clicks somewhere else.
  const saved = await getJSON(`/api/runs/${name}/analysis`);
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
});

document.getElementById("run-select").addEventListener("change", (event) => chooseRun(event.target.value));

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

document.getElementById("analyze").addEventListener("click", async () => {
  state.analysis = await getJSON(`/api/runs/${state.run}/analysis`);
  fillTable(state.analysis);
  render();
  showStep(2);
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
  let received = 0;
  state.stream = new EventSource(`/api/runs/${state.run}/candidates/stream`);
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
  });
  state.stream.onerror = () => {
    progress.textContent = "The candidate stream stopped unexpectedly.";
    state.stream.close();
  };
}

document.getElementById("to-candidates").addEventListener("click", () => {
  showStep(3);
  streamCandidates();
});

document.getElementById("back-to-2").addEventListener("click", () => {
  if (state.stream) state.stream.close();
  showStep(2);
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
