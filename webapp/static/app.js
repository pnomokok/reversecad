// ReverseCAD front end: screens 1-2 in replay mode (saved runs, no API calls).
// Screen 1: choose a saved run, click the part, enter the thickness.
// Screen 2: card, part outline and holes drawn over the photo, measurement table beside it.

const state = { run: null, image: null, click: null, analysis: null };
const canvas = document.getElementById("photo-canvas");
const context = canvas.getContext("2d");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function showStep(step) {
  document.querySelectorAll("#steps li").forEach((li) => li.classList.toggle("active", li.dataset.step === String(step)));
  document.getElementById("screen-1").classList.toggle("hidden", step !== 1);
  document.getElementById("screen-2").classList.toggle("hidden", step !== 2);
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
