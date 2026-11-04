// Parts gallery: a card per finished run with a rotating 3D preview of its result model.
// Click a card to open that run in the existing replay flow (edit screen). Every number on
// a card comes from the run's saved files via /api/parts; previews build through the same
// endpoint as the Edit screen, with the result program's own defaults.
import { createTurntable } from "./viewer.js";

const esc = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const inViewport = (element) => {
  const box = element.getBoundingClientRect();
  return box.bottom > 0 && box.top < window.innerHeight;
};

let observer = null;
const previews = new Map();  // run name -> { card, stl } ; turntables come and go with scrolling

function cardHTML(part) {
  const holes = part.hole_count === 1 ? "1 hole" : `${part.hole_count} holes`;
  return `<span class="part-preview"><span class="preview-status">Building…</span></span>`
    + `<span class="part-name" title="${esc(part.title || part.name)} (${esc(part.name)})">${esc(part.title || part.name)}</span>`
    + `<span class="part-facts" title="Outline measured from the photo">Measured ${part.length_mm.toFixed(2)} × ${part.width_mm.toFixed(2)} mm · ${holes}</span>`
    + `<span class="part-chips"><span class="status-chip">${esc(part.source)}</span>`
    + `<span class="status-chip">${esc(part.kind)}</span></span>`;
}

function ensurePreview(name) {
  // A visible card with its model bytes gets a turntable (created once per showing).
  const entry = previews.get(name);
  if (!entry || !entry.stl || entry.turn) return;
  entry.turn = createTurntable(entry.preview);
  entry.turn.show(entry.stl);
  entry.preview.querySelector(".preview-status")?.remove();
}

function releasePreview(name) {
  // A card scrolled away loses its turntable (its WebGL context too); the bytes stay cached.
  const entry = previews.get(name);
  if (entry?.turn) {
    entry.turn.dispose();
    entry.turn = null;
  }
}

async function fetchModel(name) {
  // The result model with the program's own defaults, exactly what the Edit screen builds.
  const response = await fetch(`/api/runs/${encodeURIComponent(name)}/model`,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ parameters: {} }) });
  if (!response.ok) throw new Error(await response.text());
  return response.arrayBuffer();
}

export async function showParts(grid, statusEl, { setScreen, openRun }) {
  if (observer) observer.disconnect();
  for (const name of previews.keys()) releasePreview(name);
  previews.clear();
  grid.innerHTML = "";
  setScreen("parts");
  statusEl.textContent = "Loading parts…";
  const { parts } = await (await fetch("/api/parts")).json();
  statusEl.textContent = parts.length === 1 ? "1 part" : `${parts.length} parts`;
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) ensurePreview(entry.target.dataset.run);
      else releasePreview(entry.target.dataset.run);
    }
  }, { rootMargin: "300px" });
  await Promise.all(parts.map(async (part) => {
    const card = document.createElement("button");
    card.className = "part-card";
    card.dataset.run = part.name;
    card.innerHTML = cardHTML(part);
    card.addEventListener("click", () => openRun(part.name));
    grid.appendChild(card);
    const entry = { card, preview: card.querySelector(".part-preview"), stl: null, turn: null };
    previews.set(part.name, entry);
    observer.observe(card);
    try {
      entry.stl = await fetchModel(part.name);
    } catch {
      entry.preview.querySelector(".preview-status").textContent = "Preview unavailable";
      return;
    }
    if (inViewport(card)) ensurePreview(part.name);  // above the fold: no wait for the observer
  }));
}
