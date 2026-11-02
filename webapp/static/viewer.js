// 3D viewer for the Edit screen: the built part (STL) in an isometric orthographic view, with dimension
// lines and labels pinned to 3D points (three.js CSS2DRenderer). The numbers come from the built model
// itself: its bounding box (length, width, thickness) and its top-face holes (from the back end).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import { CSS2DObject, CSS2DRenderer } from "three/addons/renderers/CSS2DRenderer.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const ISO = new THREE.Vector3(1, -1, 0.9).normalize();  // looking at the front (-y) and right (+x) faces
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

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
  let mating = null;
  let annotations = null;
  let framedRadius = null;
  let labelsVisible = true;  // dimension labels on/off (toolbar toggle, default on)
  let changed = new Set();
  const labelElements = {};  // key -> element, so "changed" can be toggled without a rebuild

  function resize() {
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    renderer.setSize(width, height);
    labels.setSize(width, height);
    if (assembly && part) fitProjected(framedBox(), framedBox().getCenter(new THREE.Vector3()));
    else if (framedRadius) setFrustum(framedRadius);
  }

  function setFrustum(radius) {
    const [width, height] = [container.clientWidth || 800, container.clientHeight || 600];
    const half = radius * 1.35;  // room around the part for the dimension labels
    Object.assign(camera, { left: -half * width / height, right: half * width / height, top: half, bottom: -half });
    if (shiftRight) camera.setViewOffset(width, height, -shiftRight, 0, width, height);
    camera.updateProjectionMatrix();
  }

  function framedBox() {
    // What the view frames: the assembly stack in sim view (padded for its outside tags),
    // else the part and its ghosts.
    if (assembly) return new THREE.Box3().setFromObject(assembly).expandByScalar(10);
    const box = new THREE.Box3().setFromObject(part);
    if (companion) box.expandByObject(companion);
    if (mating) box.expandByObject(mating);
    return box;
  }

  function setView(view, box = part && framedBox()) {
    if (!box) return;
    const center = box.getCenter(new THREE.Vector3());
    const radius = box.getSize(new THREE.Vector3()).length() / 2;
    framedRadius = radius;
    camera.zoom = 1;
    controls.target.copy(center);
    if (view === "top") {
      camera.up.set(0, 1, 0);
      camera.position.copy(center).add(new THREE.Vector3(0, 0, radius * 4));
      camera.lookAt(center);  // orient first: fitProjected reads the camera's orientation
    } else if (view === "iso") {
      camera.up.set(0, 0, 1);
      camera.position.copy(center).addScaledVector(ISO, radius * 4);
      camera.lookAt(center);
    }
    if (assembly) fitProjected(box, center);
    else setFrustum(radius);
    camera.updateProjectionMatrix();
    controls.update();
    if (assembly) layoutSimLabels();  // tags follow the current view, screws stay put
  }

  function fitProjected(box, center) {
    // As in the gallery turntables: project the box's corners and fit so the largest extent fills
    // 80% of the viewer. The sim camera stays where the user left it, so only the current view is
    // fitted (the Fit button refits after orbiting); the picture shifts right of the left overlay.
    camera.updateMatrixWorld();
    const centerCam = center.clone().applyMatrix4(camera.matrixWorldInverse);
    const corner = new THREE.Vector3();
    let hw = 0;
    let hh = 0;
    for (const x of [box.min.x, box.max.x])
      for (const y of [box.min.y, box.max.y])
        for (const z of [box.min.z, box.max.z]) {
          corner.set(x, y, z).applyMatrix4(camera.matrixWorldInverse).sub(centerCam);
          hw = Math.max(hw, Math.abs(corner.x));
          hh = Math.max(hh, Math.abs(corner.y));
        }
    const width = container.clientWidth || 800;
    const height = container.clientHeight || 600;
    const half = Math.max(hh, (hw * height) / width) / 0.8;
    camera.aspect = width / height;
    camera.left = (-half * width) / height;
    camera.right = (half * width) / height;
    camera.top = half;
    camera.bottom = -half;
    if (shiftRight) camera.setViewOffset(width, height, -shiftRight, 0, width, height);
    camera.updateProjectionMatrix();
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

    // Holes: one label per diameter, each pinned to that diameter's hole nearest the viewer's
    // side and stacked with a two-gap step, so no two labels overlap in the iso view.
    const groups = new Map();
    for (const hole of features.holes) {
      const key = hole.diameter.toFixed(2);
      groups.set(key, [...(groups.get(key) || []), hole]);
    }
    if (!features.holes.length) return group;
    const nearest = (holes) => holes.reduce((a, b) => (b.center[0] - b.center[1] > a.center[0] - a.center[1] ? b : a));
    let lift = 0;
    for (const [diameter, holes] of groups) {
      const [hx, hy, hz] = nearest(holes).center;
      const end = [hx + gap * (0.5 + 2.2 * lift), hy + gap * 0.2, hz + gap * (1.1 + 2.2 * lift)];
      group.add(line([[hx, hy, hz], end], dimensionMaterial));
      group.add(label("hole", `${holes.length > 1 ? `${holes.length}× ` : ""}Ø${Number(diameter).toFixed(2)} mm`, end));
      lift += 1;
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
    if (!assembly) scene.add(part);  // in sim view the rebuilt part waits detached
    if (features) {
      annotations = annotate(features);
      if (!assembly) scene.add(annotations);
    }
    if (annotations) annotations.visible = labelsVisible;
    if (!framedRadius) {  // first show: the part rises from its flat outline while the camera swings down
      if (reducedMotion()) setView("iso");
      else riseFromTop();
    }
    else {  // slider rebuilds keep the view, unless the part outgrew the frame or shrank to less than
      // half of it: then the frustum is refit (direction kept) so a small part is never left tiny.
      const radius = framedBox().getSize(new THREE.Vector3()).length() / 2;
      if (radius < framedRadius * 0.5 || radius > framedRadius * 1.35) setView();
    }
  }

  const companionMaterial = new THREE.MeshStandardMaterial({
    color: css("--color-model"), transparent: true, opacity: 0.3, metalness: 0, roughness: 0.75, depthWrite: false,
  });

  function clearGhost(group) {
    if (!group) return null;
    scene.remove(group);
    group.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.isCSS2DObject) o.element.remove();
    });
    return null;
  }

  function makeGhost(stlBuffer, labelText, liftZ) {
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    geometry.computeBoundingBox();
    const box = geometry.boundingBox;
    const group = new THREE.Group();
    group.add(new THREE.Mesh(geometry, companionMaterial));
    group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edgeMaterial));
    group.position.z = liftZ;
    if (labelText) {
      const element = document.createElement("div");
      element.className = "dim-label";
      element.textContent = labelText;
      const tag = new CSS2DObject(element);
      tag.position.set(box.getCenter(new THREE.Vector3()).x, box.max.y, box.max.z);
      group.add(tag);
    }
    if (!assembly) scene.add(group);
    return group;
  }

  function showCompanion(stlBuffer, labelText = null, { overlay = false, liftZ = 0 } = {}) {
    // The original next to a matching part: see-through, behind it along +Y, clear of the largest outline
    // offset the slider allows (+10 mm on both parts' facing edges); null hides it. With overlay (the
    // adapter), it sits at the same XY instead, lifted by liftZ, so it covers its pattern exactly.
    companion = clearGhost(companion);
    if (!stlBuffer) return;
    companion = makeGhost(stlBuffer, labelText, overlay ? liftZ : 0);
    if (!overlay) {
      const size = new THREE.Box3().setFromObject(companion).getSize(new THREE.Vector3());
      companion.position.y = size.y + Math.max(size.y * 0.4, 16);
    }
  }

  function showMating(stlBuffer, labelText = null, liftZ = 0) {
    // The mating plate over an adapter's pattern B: same XY as built, lifted by liftZ; null hides it.
    mating = clearGhost(mating);
    if (!stlBuffer) return;
    mating = makeGhost(stlBuffer, labelText, liftZ);
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
    if (!assembly) scene.add(suggestion);
  }

  // ---------- assembly check simulation ----------
  // The stack (original + adapter + mating plate) with its screws, built from the check's STLs
  // (all in stack coordinates). Screws start as steel and take their verdict color: green passes,
  // red glows with the computed clash solids. Task-specified sim colors, not theme variables.
  const SIM_STEEL = 0x9aa0a6;
  const SIM_PASS = 0x46a758;
  const SIM_BLOCKED = 0xe5484d;
  let assembly = null;
  let assemblyToken = 0;
  let assemblyPlates = [];  // plate groups (tags are re-placed on every view change)
  let assemblyScrewLabels = [];  // blocked-screw CSS2DObjects: obstacles when placing tags
  let assemblyTags = [];  // {group, tag, leader} of the current plate tags, for re-layout

  const clashMaterial = () => new THREE.MeshStandardMaterial({
    color: SIM_BLOCKED, emissive: SIM_BLOCKED, emissiveIntensity: 0.55, transparent: true,
    opacity: 0, metalness: 0, roughness: 0.5, depthWrite: false,
  });

  function clearAssembly() {
    assemblyToken += 1;  // stale animation frames stop themselves
    if (!assembly) return;
    scene.remove(assembly);
    assembly.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      if (o.isCSS2DObject) o.element.remove();
      if (o.isMesh && o.userData.ownedMaterial) o.material.dispose?.();
    });
    assembly = null;
    assemblyPlates = [];
    assemblyScrewLabels = [];
    assemblyTags = [];
  }

  function simLabel(text, position, small = false) {
    const element = document.createElement("div");
    element.className = small ? "dim-label sim-screw-label" : "dim-label";
    element.textContent = text;
    const object = new CSS2DObject(element);
    object.position.set(...position);
    return object;
  }

  function setDomLabels(group, visible) {
    // CSS2DRenderer only updates labels it traverses, so a group leaving the scene would leave
    // its labels behind; hide them by hand (showing again is the renderer's job after re-attach).
    group.traverse((o) => {
      if (o.isCSS2DObject) o.element.style.display = visible ? "" : "none";
    });
  }

  function layoutSimLabels() {
    // (Re)place the plate tags for the current camera: each tag gets its own outside corner of
    // the stack with a leader to its plate's nearest corner (like the dimension labels), skipping
    // the corner nearest the floating overlay panel. Tags are then clamped into the visible strip
    // and lifted past screw labels and each other, so no two labels overlap in any view.
    for (const { group, tag, leader } of assemblyTags) {
      group.remove(tag);
      tag.element.remove();
      group.remove(leader);
      leader.geometry.dispose();
    }
    assemblyTags = [];
    if (!assemblyPlates.length) return;
    const stack = new THREE.Box3();
    for (const group of assemblyPlates) stack.union(group.userData.box);
    camera.updateMatrixWorld();
    const mid = { x: (stack.min.x + stack.max.x) / 2, y: (stack.min.y + stack.max.y) / 2, z: (stack.min.z + stack.max.z) / 2 };
    const viewRect = container.getBoundingClientRect();
    const insetRect = document.querySelector(".fit-inset")?.getBoundingClientRect();
    const clearLeft = (insetRect ? insetRect.right - viewRect.left : 0) + 78;
    const clearRight = viewRect.width - 78;
    const camRight = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    const camUp = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    const mmPerPxX = (camera.right - camera.left) / (container.clientWidth || 800);
    const mmPerPxY = (camera.top - camera.bottom) / (container.clientHeight || 600);
    const project = (p) => {
      const v = new THREE.Vector3(...p).project(camera);
      return [(v.x * 0.5 + 0.5) * viewRect.width, (-v.y * 0.5 + 0.5) * viewRect.height];
    };
    const screenX = ([cx, cy]) => new THREE.Vector3(cx, cy, mid.z).project(camera).x;
    const stackCorners = [[stack.min.x, stack.min.y], [stack.max.x, stack.min.y],
      [stack.min.x, stack.max.y], [stack.max.x, stack.max.y]]
      .sort((a, b) => screenX(b) - screenX(a)).slice(0, 3);
    // Label half-sizes on screen (px): plate tags are wide, screw labels small; screws never move.
    const placed = assemblyScrewLabels.map((o) => [...project(o.position.toArray()), 20, 14]);
    assemblyPlates.forEach((group, i) => {
      const box = group.userData.box;
      const corner = stackCorners[i % 3];
      const outward = new THREE.Vector2(corner[0] - mid.x, corner[1] - mid.y).normalize();
      const tagAt = [corner[0] + outward.x * 8, corner[1] + outward.y * 8, box.max.z + 1.5];
      for (let nudge = 0; nudge < 24; nudge++) {
        const sx = project(tagAt)[0];
        if (sx >= clearLeft && sx <= clearRight) break;
        const step = Math.sign(sx < clearLeft ? clearLeft - sx : clearRight - sx) * mmPerPxX * 8;
        tagAt[0] += camRight.x * step;
        tagAt[1] += camRight.y * step;
        tagAt[2] += camRight.z * step;
      }
      for (let lift = 0; lift < 12; lift++) {
        const [sx, sy] = project(tagAt);
        const hit = placed.find(([px, py, pw, ph]) =>
          Math.abs(sx - px) < pw + 58 + 6 && Math.abs(sy - py) < ph + 16 + 6);
        if (!hit) break;
        const dir = sy <= hit[1] ? 1 : -1;  // lift away from the label underneath
        const step = ((hit[3] + 16 + 6) - Math.abs(sy - hit[1]) + 2) * mmPerPxY * dir;
        tagAt[0] += camUp.x * step;
        tagAt[1] += camUp.y * step;
        tagAt[2] += camUp.z * step;
      }
      placed.push([...project(tagAt), 58, 16]);
      const own = [box.min.x, box.min.y, box.max.x, box.max.y];
      const foot = [(Math.abs(own[0] - tagAt[0]) < Math.abs(own[2] - tagAt[0]) ? own[0] : own[2]),
        (Math.abs(own[1] - tagAt[1]) < Math.abs(own[3] - tagAt[1]) ? own[1] : own[3]), box.max.z];
      const leader = line([foot, tagAt], dimensionMaterial);
      const tag = simLabel(group.userData.tag, tagAt);
      group.add(leader);
      group.add(tag);
      assemblyTags.push({ group, tag, leader });
    });
  }

  function showAssembly(data, { intro = true, onDone = null } = {}) {
    // data: {plates: [{buffer, tag}], screws: [{id, x, y, buffer, verdict, clashes: [buffers]}]}.
    // With intro the parts start exploded along Z and ease together, then the screws slide in
    // one by one and take their verdict colors; without intro everything starts assembled and
    // only the colors animate (toggle re-runs). onDone runs last, after the colors settle.
    // Plates are see-through so the screws and clashes inside the stack stay visible.
    clearAssembly();
    for (const group of [part, annotations, companion, mating, suggestion]) {
      if (group) {
        setDomLabels(group, false);
        scene.remove(group);
      }
    }
    const token = assemblyToken;
    assembly = new THREE.Group();
    const plates = data.plates.map(({ buffer, tag }, i) => {
      const geometry = new STLLoader().parse(buffer);
      geometry.computeVertexNormals();
      const shell = new THREE.MeshStandardMaterial({
        color: 0xd7d3d0, metalness: 0.6, roughness: 0.4, transparent: true, opacity: 0.32,
        depthWrite: false,
      });
      const mesh = new THREE.Mesh(geometry, shell);
      mesh.userData.ownedMaterial = true;
      const group = new THREE.Group();
      group.add(mesh);
      group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edgeMaterial));
      geometry.computeBoundingBox();
      group.userData.box = geometry.boundingBox.clone();
      group.userData.tag = tag;
      group.userData.explode = i * 16;  // mm above its stacked seat, eased to 0
      assembly.add(group);
      return group;
    });
    assemblyPlates = plates;
    assemblyScrewLabels = [];
    const screws = data.screws.map(({ id, buffer, verdict, clashes }) => {
      const geometry = new STLLoader().parse(buffer);
      geometry.computeVertexNormals();
      const paint = new THREE.MeshStandardMaterial({
        color: SIM_STEEL, metalness: 0.85, roughness: 0.35, emissive: SIM_STEEL, emissiveIntensity: 0,
      });
      const group = new THREE.Group();
      const bolt = new THREE.Mesh(geometry, paint);
      bolt.userData.ownedMaterial = true;
      group.add(bolt);
      geometry.computeBoundingBox();
      const box = geometry.boundingBox;
      // Only blocked screws are labeled; passing ones read clearly from their green color.
      if (verdict === "blocked") {
        const screwLabel = simLabel(id, [(box.min.x + box.max.x) / 2, (box.min.y + box.max.y) / 2, box.max.z + 1.5], true);
        group.add(screwLabel);
        assemblyScrewLabels.push(screwLabel);
      }
      const overlays = (clashes || []).map((clash) => {
        const overlay = new THREE.Mesh(new STLLoader().parse(clash), clashMaterial());
        overlay.userData.ownedMaterial = true;
        group.add(overlay);
        return overlay;
      });
      group.userData = { paint, overlays, verdict, drop: 34 };
      assembly.add(group);
      return group;
    });
    scene.add(assembly);
    setView(undefined, framedBox());  // also (re)places the plate tags for this camera
    if (intro) {
      for (const group of plates) group.position.z = group.userData.explode;
      for (const group of screws) group.position.z = group.userData.drop;
    }
    const finish = () => {
      if (token !== assemblyToken) return;
      for (const group of [...plates, ...screws]) group.position.z = 0;
      for (const group of screws) paintVerdict(group, 1);
      if (onDone) onDone();
    };
    if (reducedMotion()) { finish(); return; }
    const t0 = performance.now();
    const eased = (t) => 1 - Math.pow(1 - t, 3);
    const screwStart = intro ? 750 : 0;
    const step = (now) => {
      if (token !== assemblyToken) return;
      const elapsed = now - t0;
      let busy = false;
      plates.forEach((group, i) => {
        const t = intro ? Math.min(1, Math.max(0, (elapsed - 90 * i) / 700)) : 1;
        group.position.z = group.userData.explode * (1 - eased(t));
        if (t < 1) busy = true;
      });
      screws.forEach((group, i) => {
        const begin = screwStart + 170 * i;
        const t = Math.min(1, Math.max(0, (elapsed - begin) / (intro ? 380 : 450)));
        if (intro) group.position.z = group.userData.drop * (1 - eased(t));
        paintVerdict(group, intro ? (t >= 1 ? 1 : 0) : eased(t));
        if (t < 1) busy = true;
      });
      if (busy) requestAnimationFrame(step);
      else finish();
    };
    requestAnimationFrame(step);
  }

  function paintVerdict(group, k) {
    // A screw's steel fades to its verdict color; a blocked screw also glows with its clashes.
    const { paint, overlays, verdict } = group.userData;
    const target = new THREE.Color(verdict === "blocked" ? SIM_BLOCKED : SIM_PASS);
    paint.color.copy(new THREE.Color(SIM_STEEL).lerp(target, k));
    paint.emissive.copy(target);
    paint.emissiveIntensity = verdict === "blocked" ? 0.55 * k : 0.12 * k;
    for (const overlay of overlays) overlay.material.opacity = 0.75 * k;
  }

  function hideAssembly() {
    // Back to the part view: the sim group goes away, the part and its company come back.
    clearAssembly();
    for (const group of [part, annotations, companion, mating, suggestion]) {
      if (group) {
        scene.add(group);
        setDomLabels(group, true);
      }
    }
    if (part) setView();
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

  function riseFromTop() {
    // Model-ready transition on the real geometry: flat outline to full thickness, top view to iso.
    const box = framedBox();
    const center = box.getCenter(new THREE.Vector3());
    const radius = box.getSize(new THREE.Vector3()).length() / 2;
    framedRadius = radius;
    setFrustum(radius);
    camera.zoom = 1;
    controls.target.copy(center);
    camera.up.set(0, 0, 1);
    const topPos = center.clone().add(new THREE.Vector3(0, 0, radius * 4));
    const isoPos = center.clone().addScaledVector(ISO, radius * 4);
    camera.position.copy(topPos).lerp(isoPos, 0.02);  // a touch off the exact top, so "up" stays valid
    camera.updateProjectionMatrix();
    controls.update();
    part.scale.z = 0.02;
    if (annotations) annotations.scale.z = 0.02;
    controls.enabled = false;
    const t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / 1100);
      const eased = 1 - Math.pow(1 - t, 3);
      camera.position.copy(topPos).lerp(isoPos, 0.02 + 0.98 * eased);
      part.scale.z = 0.02 + 0.98 * eased;
      if (annotations) annotations.scale.z = part.scale.z;
      camera.updateProjectionMatrix();
      controls.update();
      if (t < 1) requestAnimationFrame(step);
      else {
        part.scale.z = 1;
        if (annotations) annotations.scale.z = 1;
        controls.enabled = true;
      }
    };
    requestAnimationFrame(step);
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
  return { show, showCompanion, showMating, showSuggestion, showAssembly, hideAssembly,
    assemblyActive: () => !!assembly, resize, setView, setChanged, previewLabel, triangleCount,
    setLabelsVisible: (visible) => {
      // CSS2DRenderer only honours each label's own visibility, never a parent group's, so the HTML
      // labels are hidden via their container; the drawn dimension/leader lines via the group itself.
      labelsVisible = visible;
      labels.domElement.style.display = visible ? "" : "none";
      if (annotations) annotations.visible = visible;
    },
    reset: () => { framedRadius = null; } };
}

// ---------- card previews: small turntables for the Parts gallery ----------
// Each card owns a small renderer (created when scrolled into view), but one shared
// requestAnimationFrame loop rotates and renders every visible one, so 10+ cards stay
// smooth. With prefers-reduced-motion a card renders one static iso frame, never looping.
const turntables = new Set();
let turntableFrame = null;
const TURNTABLE_PERIOD_S = 14;  // one slow revolution

function tickTurntables() {
  turntableFrame = null;
  let alive = false;
  for (const turn of turntables) alive = turn.tick() || alive;
  if (alive) turntableFrame = requestAnimationFrame(tickTurntables);
}

function pokeTurntables() {
  if (!turntableFrame && !reducedMotion()) turntableFrame = requestAnimationFrame(tickTurntables);
}

export function createTurntable(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  container.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -5000, 5000);
  camera.up.set(0, 0, 1);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x3a3f44, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(0.6, -1, 1.6);
  scene.add(sun);
  const material = new THREE.MeshStandardMaterial({ color: css("--color-model"), metalness: 0, roughness: 0.75 });
  const edgeMaterial = new THREE.LineBasicMaterial({ color: css("--color-model-edge") });
  let part = null;
  let center = new THREE.Vector3();
  let radius = 1;
  let frame = null;  // largest projected half-extents of the bounding box over a revolution
  let visible = true;
  const t0 = performance.now();
  const api = { show, setVisible, resize, dispose, tick };

  function measureFrame() {
    // How large the bounding box ever appears while the camera circles it: project its
    // corners at 16 angles and keep the largest half-width (hw) and half-height (hh).
    const box = new THREE.Box3().setFromObject(part);
    const corners = [];
    for (const x of [box.min.x, box.max.x])
      for (const y of [box.min.y, box.max.y])
        for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z).sub(center));
    const probe = new THREE.OrthographicCamera(-1, 1, 1, -1, -5000, 5000);
    probe.up.set(0, 0, 1);
    const corner = new THREE.Vector3();
    let hw = 0;
    let hh = 0;
    for (let i = 0; i < 16; i++) {
      probe.position.copy(center).addScaledVector(
        ISO.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), (i / 16) * Math.PI * 2), radius * 4);
      probe.lookAt(center);
      probe.updateMatrixWorld();
      for (const offset of corners) {
        corner.copy(offset).applyMatrix4(probe.matrixWorldInverse);
        hw = Math.max(hw, Math.abs(corner.x));
        hh = Math.max(hh, Math.abs(corner.y));
      }
    }
    frame = { hw, hh };
  }

  function fit() {
    const width = container.clientWidth || 300;
    const height = container.clientHeight || 170;
    renderer.setSize(width, height);
    // The widest projected extent fills 80% of the preview; nothing clips at any angle.
    const half = Math.max(frame.hh, (frame.hw * height) / width) / 0.8;
    Object.assign(camera, { left: -half * width / height, right: half * width / height, top: half, bottom: -half });
    camera.updateProjectionMatrix();
  }

  function render(now) {
    if (!part || !visible) return;
    // The camera circles the part around the Z axis, starting from the iso direction.
    const angle = reducedMotion() ? 0 : ((now - t0) / 1000 / TURNTABLE_PERIOD_S) * Math.PI * 2;
    camera.position.copy(center).addScaledVector(
      ISO.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), angle), radius * 4);
    camera.lookAt(center);
    renderer.render(scene, camera);
  }

  function show(stlBuffer) {
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    part = new THREE.Group();
    part.add(new THREE.Mesh(geometry, material));
    part.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), edgeMaterial));
    const box = new THREE.Box3().setFromObject(part);
    center = box.getCenter(new THREE.Vector3());
    radius = box.getSize(new THREE.Vector3()).length() / 2;
    scene.add(part);
    measureFrame();
    fit();
    render(performance.now());
    pokeTurntables();
  }

  function tick() {
    if (!part || !visible || reducedMotion()) return false;
    render(performance.now());
    return true;
  }

  function setVisible(value) {
    visible = value;
    if (value && part) { fit(); render(performance.now()); pokeTurntables(); }
  }

  function resize() {
    if (part) { fit(); render(performance.now()); }
  }

  function dispose() {
    turntables.delete(api);
    window.removeEventListener("resize", resize);
    if (part) part.traverse((o) => o.geometry && o.geometry.dispose());
    part = null;
    renderer.dispose();
    renderer.domElement.remove();
  }

  turntables.add(api);
  window.addEventListener("resize", resize);
  return api;
}
