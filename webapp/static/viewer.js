// 3D viewer for screen 4: shows an STL (from the back end) with three.js, mouse to orbit and zoom.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export function createViewer(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(css("--color-viewer-bg"));
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
  const controls = new OrbitControls(camera, renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x444444, 2.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.5);
  sun.position.set(1, 1, 2);
  scene.add(sun);

  const material = new THREE.MeshStandardMaterial({ color: css("--color-model"), metalness: 0.2, roughness: 0.6 });
  let mesh = null;
  let framed = false;

  function resize() {
    const width = container.clientWidth;
    const height = container.clientHeight || 560;  // the box's height comes from app.css (--viewer-height)
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function frame(geometry) {
    // Point the camera at the part from above and to the side, at a distance that fits it.
    geometry.computeBoundingSphere();
    const { center, radius } = geometry.boundingSphere;
    controls.target.copy(center);
    camera.position.set(center.x + radius * 1.2, center.y - radius * 1.6, center.z + radius * 1.8);
    camera.up.set(0, 0, 1);
    controls.update();
  }

  function show(stlBuffer) {
    const geometry = new STLLoader().parse(stlBuffer);
    geometry.computeVertexNormals();
    if (mesh) {
      scene.remove(mesh);
      mesh.geometry.dispose();
    }
    mesh = new THREE.Mesh(geometry, material);
    scene.add(mesh);
    if (!framed) {  // keep the user's view when a slider rebuilds the part
      frame(geometry);
      framed = true;
    }
  }

  function loop() {
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }

  window.addEventListener("resize", resize);
  resize();
  loop();
  return { show, resize, reset: () => { framed = false; } };
}
