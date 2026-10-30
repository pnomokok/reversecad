// 3D viewer for the Edit screen: the built part (STL) in an isometric orthographic view, with dimension
// lines and labels pinned to 3D points (three.js CSS2DRenderer). The numbers come from the built model
// itself: its bounding box (length, width, thickness) and its top-face holes (from the back end).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ISO = new THREE.Vector3(1, -1, 0.9).normalize();  // looking at the front (-y) and right (+x) faces

// shiftRight (px) moves the picture right, to keep the part clear of an overlay on the left.
export function createViewer(container, { shiftRight = 0 } = {}) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);
  const labels = new CSS2DRenderer();
  Object.assign(labels.domElement.style, { position: "absolute", top: "0", left: "0", pointerEvents: "none" });
  container.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -5000, 5000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3f44, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(0.6, -1, 1.6);
  scene.add(sun);

  const material = new THREE.MeshStandardMaterial({ color: css("--color-model"), metalness: 0, roughness: 0.75 });
  const edgeMaterial = new THREE.LineBasicMaterial({ color: css("--color-model-edge") });
  const dimensionMaterial = new THREE.LineBasicMaterial({ color: css("--color-dimension-line") });
  const extensionMaterial = new THREE.LineDashedMaterial({ color: css("--color-extension-line"), dashSize: 1.2, gapSize: 1.2 });

  let part = null;
  let companion = null;
  let annotations = null;
  let framedRadius = null;
  let changed = new Set();
  const labelElements = {};  // key -> element, so "changed" can be toggled without a rebuild

  function resize() {
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    renderer.setSize(width, height);
    labels.setSize(width, height);
    if (framedRadius) setFrustum(framedRadius);
  }

  function setFrustum(radius) {
    const [width, height] = [container.clientWidth || 800, container.clientHeight || 600];
    const half = radius * 1.35;  // room around the part for the dimension labels
    Object.assign(camera, { left: -half * width / height, right: half * width / height, top: half, bottom: -half });
    if (shiftRight) camera.setViewOffset(width, height, -shiftRight, 0, width, height);
    camera.updateProjectionMatrix();
  }

  function framedBox() {
    // What the view frames: the part and, if shown, the see-through original next to it.
    const box = new THREE.Box3().setFromObject(part);
    return companion ? box.expandByObject(companion) : box;
  }

  function setView(view, box = part && framedBox()) {
    if (!box) return;
    const center = box.getCenter(new THREE.Vector3());
    const radius = box.getSize(new THREE.Vector3()).length() / 2;
    framedRadius = radius;
    setFrustum(radius);
    camera.zoom = 1;
    controls.target.copy(center);
    if (view === "top") {
      camera.up.set(0, 1, 0);
      camera.position.copy(center).add(new THREE.Vector3(0, 0, radius * 4));
    } else if (view === "iso") {
      camera.up.set(0, 0, 1);
      camera.position.copy(center).addScaledVector(ISO, radius * 4);
    }
    camera.updateProjectionMatrix();
    controls.update();
  }

  function line(points, lineMaterial) {
    const geometry = new THREE.BufferGeometry().setFromPoints(points.map((p) => new THREE.Vector3(...p)));
    const object = new THREE.Line(geometry, lineMaterial);
    if (lineMaterial.isLineDashedMaterial) object.computeLineDistances();
    return object;
  }

  function label(key, text, position) {
    const element = document.createElement("div");
    element.className = "dim-label";
    element.textContent = text;
    element.classList.toggle("changed", changed.has(key));
    labelElements[key] = element;
    const object = new CSS2DObject(element);
    object.position.set(...position);
    return object;
  }

  function dimension(group, key, text, from, to, offset) {
    // A dimension line parallel to from→to, moved by `offset`, with extension lines and a label.
    const a = from.map((v, i) => v + offset[i]);
    const b = to.map((v, i) => v + offset[i]);
    const reach = offset.map((v) => v * 1.25);
    group.add(line([from, from.map((v, i) => v + reach[i])], extensionMaterial));
    group.add(line([to, to.map((v, i) => v + reach[i])], extensionMaterial));
    group.add(line([a, b], dimensionMaterial));
    group.add(label(key, text, a.map((v, i) => (v + b[i]) / 2)));
  }

  function annotate(features) {
    const [x0, y0, z0, x1, y1, z1] = features.box;
    const size = Math.max(x1 - x0, y1 - y0);
    const gap = size * 0.14;
    const group = new THREE.Group();
    dimension(group, "length", `${(x1 - x0).toFixed(2)} mm`, [x0, y0, z0], [x1, y0, z0], [0, -gap, 0]);
    dimension(group, "width", `${(y1 - y0).toFixed(2)} mm`, [x1, y0, z0], [x1, y1, z0], [gap, 0, 0]);
    dimension(group, "thickness", `${(z1 - z0).toFixed(2)} mm`, [x0, y0, z0], [x0, y0, z1], [-gap * 0.7, -gap * 0.7, 0]);

    // Holes: one label per diameter, pinned with a leader to the hole nearest the viewer's side.
    const groups = new Map();
    for (const hole of features.holes) {
      const key = hole.diameter.toFixed(2);
      groups.set(key, [...(groups.get(key) || []), hole]);
    }
    let lift = 0;
    for (const [diameter, holes] of groups) {
      const hole = holes.reduce((a, b) => (b.center[0] - b.center[1] > a.center[0] - a.center[1] ? b : a));
      const [hx, hy, hz] = hole.center;
      const end = [hx + gap * 0.5, hy + gap * 0.2, hz + gap * (1.1 + lift)];
      group.add(line([[hx, hy, hz], end], dimensionMaterial));
      group.add(label("hole", `${holes.length > 1 ? `${holes.length}× ` : ""}Ø${Number(diameter).toFixed(2)} mm`, end));
      lift += 0.6;
    }
    return group;
  }

  function show(stlBuffer, features) {
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    if (part) {
      scene.remove(part);
      part.traverse((o) => o.geometry && o.geometry.dispose());
    }
    if (annotations) {
      scene.remove(annotations);
      annotations.traverse((o) => { if (o.isCSS2DObject) o.element.remove(); });
    }
    part = new THREE.Group();
    part.add(new THREE.Mesh(geometry, material));
    part.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edgeMaterial));
    scene.add(part);
    if (features) {
      annotations = annotate(features);
      scene.add(annotations);
    }
    if (!framedRadius) setView("iso");  // keep the user's view when a slider rebuilds the part
  }

  const companionMaterial = new THREE.MeshStandardMaterial({
    color: css("--color-model"), transparent: true, opacity: 0.3, metalness: 0, roughness: 0.75, depthWrite: false,
  });

  function showCompanion(stlBuffer, labelText = null) {
    // The original next to a matching part: see-through, behind it along +Y, clear of the largest outline
    // offset the slider allows (+10 mm on both parts' facing edges); null hides it.
    if (companion) {
      scene.remove(companion);
      companion.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.isCSS2DObject) o.element.remove();
      });
      companion = null;
    }
    if (!stlBuffer) return;
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    const size = box.getSize(new THREE.Vector3());
    companion = new THREE.Group();
    companion.add(new THREE.Mesh(geometry, companionMaterial));
    companion.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edgeMaterial));
    companion.position.y = size.y + Math.max(size.y * 0.4, 16);
    if (labelText) {
      const element = document.createElement("div");
      element.className = "dim-label";
      element.textContent = labelText;
      const tag = new CSS2DObject(element);
      tag.position.set(box.getCenter(new THREE.Vector3()).x, box.max.y, box.max.z);
      companion.add(tag);
    }
    scene.add(companion);
  }

  let suggestion = null;
  const suggestionMaterial = new THREE.MeshStandardMaterial({
    color: css("--color-selected"), transparent: true, opacity: 0.55, metalness: 0, roughness: 0.6, depthWrite: false,
  });

  function showSuggestion(stlBuffer, labelText = null) {
    // Material a completion suggestion would add, drawn in its own (orange, see-through) tone, with an
    // optional label on a leader above it; null hides it.
    if (suggestion) {
      scene.remove(suggestion);
      suggestion.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.isCSS2DObject) o.element.remove();
      });
      suggestion = null;
    }
    if (!stlBuffer) return;
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    const orange = new THREE.LineBasicMaterial({ color: css("--color-selected") });
    suggestion = new THREE.Group();
    suggestion.add(new THREE.Mesh(geometry, suggestionMaterial));
    suggestion.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), orange));
    if (labelText) {
      geometry.computeBoundingBox();
      const box = geometry.boundingBox;
      const center = box.getCenter(new THREE.Vector3());
      const lift = Math.max(box.getSize(new THREE.Vector3()).length(), 8);
      const end = center.clone().add(new THREE.Vector3(-lift * 0.6, -lift * 0.2, lift * 0.9));
      suggestion.add(line([[center.x, center.y, box.max.z], [end.x, end.y, end.z]], orange));
      const element = document.createElement("div");
      element.className = "dim-label suggestion-label";
      element.textContent = labelText;
      const tag = new CSS2DObject(element);
      tag.position.copy(end);
      suggestion.add(tag);
    }
    scene.add(suggestion);
  }

  function previewLabel(key, text) {
    // Show a proposed value on a dimension label ("4× Ø6.00 → Ø8.00 mm"); null puts the built value back.
    const element = labelElements[key];
    if (!element) return;
    if (element.dataset.built === undefined) element.dataset.built = element.textContent;
    element.textContent = typeof text === "function" ? text(element.dataset.built) : text ?? element.dataset.built;
  }

  function setChanged(keys) {
    changed = new Set(keys);
    for (const [key, element] of Object.entries(labelElements)) element.classList.toggle("changed", changed.has(key));
  }

  function loop() {
    controls.update();
    renderer.render(scene, camera);
    labels.render(scene, camera);
    requestAnimationFrame(loop);
  }

  window.addEventListener("resize", resize);
  resize();
  loop();
  // Triangles of the shown part's mesh (the STL the viewer loaded).
  const triangleCount = () => (part ? part.children[0].geometry.attributes.position.count / 3 : 0);
  return { show, showCompanion, showSuggestion, resize, setView, setChanged, previewLabel, triangleCount, reset: () => { framedRadius = null; } };
}
