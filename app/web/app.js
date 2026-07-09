import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const API = {
  state: "/api/state",
  scene: "/api/scene",
  step: "/api/simulation/step",
  pause: "/api/simulation/pause",
  resume: "/api/simulation/resume",
  reset: "/api/simulation/reset",
  axisTarget: (axisId) => `/api/axis/${axisId}/target`,
};

const AXES = [
  { id: "travel", label: "Travel", unit: "m", step: "0.1" },
  { id: "slew", label: "Slew", unit: "deg", step: "1" },
  { id: "boom_luff", label: "Luff", unit: "deg", step: "1" },
  { id: "boom_extension", label: "Extend", unit: "m", step: "0.1" },
  { id: "chute_rotate", label: "Chute", unit: "deg", step: "1" },
];

const sceneRoot = document.querySelector("#scene-root");
const viewStatus = document.querySelector("#view-status");
const simClock = document.querySelector("#sim-clock");
const axisControls = document.querySelector("#axis-controls");
const stateReadout = document.querySelector("#state-readout");
const sceneJson = document.querySelector("#scene-json");
const runButton = document.querySelector("#run-button");
const pauseButton = document.querySelector("#pause-button");
const resetButton = document.querySelector("#reset-button");
const applySceneButton = document.querySelector("#apply-scene-button");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xd6dee5);
scene.fog = new THREE.Fog(0xd6dee5, 95, 170);

const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1000);
camera.position.set(58, 44, 68);

const renderer = new THREE.WebGLRenderer({
  antialias: true,
  alpha: false,
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
sceneRoot.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(10, 7, 4);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = 24;
controls.maxDistance = 170;
controls.maxPolarAngle = Math.PI * 0.48;

const materials = {
  ground: new THREE.MeshStandardMaterial({ color: 0xbfc9d1, roughness: 0.88 }),
  rail: new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.55 }),
  railGuard: new THREE.MeshStandardMaterial({ color: 0xf97316, roughness: 0.5 }),
  loader: new THREE.MeshStandardMaterial({ color: 0xe34225, roughness: 0.45, metalness: 0.12 }),
  loaderDark: new THREE.MeshStandardMaterial({ color: 0x7c1d12, roughness: 0.55, metalness: 0.1 }),
  boom: new THREE.MeshStandardMaterial({ color: 0xf15a24, roughness: 0.42, metalness: 0.15 }),
  boomDark: new THREE.MeshStandardMaterial({ color: 0x4b5563, roughness: 0.6, metalness: 0.12 }),
  belt: new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.7 }),
  chute: new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.45, metalness: 0.1 }),
  chuteSleeve: new THREE.MeshStandardMaterial({ color: 0x93c5fd, roughness: 0.42, metalness: 0.08 }),
  discharge: new THREE.MeshStandardMaterial({ color: 0xdc2626, roughness: 0.35 }),
  shipHull: new THREE.MeshStandardMaterial({ color: 0x121826, roughness: 0.64 }),
  shipTrim: new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 }),
  holdRim: new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.62 }),
  coal: new THREE.MeshStandardMaterial({ color: 0x050505, roughness: 0.95 }),
  trajectory: new THREE.LineBasicMaterial({ color: 0x16a34a }),
};

const staticGroup = new THREE.Group();
const vesselsGroup = new THREE.Group();
const loaderGroup = new THREE.Group();
scene.add(staticGroup, vesselsGroup, loaderGroup);

let trajectoryLine = null;
let trajectoryPoints = [];
let latestSnapshot = null;
let running = true;
let stepping = false;
let tickTimer = null;

function worldToThree(value) {
  const [x, y, z] = value;
  return new THREE.Vector3(x, z, y);
}

function threeToWorld(value) {
  return [value.x, value.z, value.y];
}

function setStatus(message) {
  viewStatus.textContent = message;
}

function format(value, digits = 2) {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function clearGroup(group) {
  for (const child of [...group.children]) {
    group.remove(child);
    disposeObject(child);
  }
}

function disposeObject(object) {
  object.traverse((child) => {
    if (child.geometry) {
      child.geometry.dispose();
    }
    if (child.material && !Object.values(materials).includes(child.material)) {
      if (Array.isArray(child.material)) {
        child.material.forEach((material) => material.dispose());
      } else {
        child.material.dispose();
      }
    }
  });
}

function addBox(parent, center, size, material, rotationY = 0) {
  const geometry = new THREE.BoxGeometry(size.x, size.y, size.z);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(center);
  mesh.rotation.y = rotationY;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function addWorldBox(parent, centerWorld, sizeWorld, material) {
  return addBox(
    parent,
    worldToThree(centerWorld),
    new THREE.Vector3(sizeWorld.x, sizeWorld.z, sizeWorld.y),
    material,
  );
}

function addVerticalCylinder(parent, centerWorld, radius, height, material, segments = 32) {
  const geometry = new THREE.CylinderGeometry(radius, radius, height, segments);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(worldToThree(centerWorld));
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function addCylinderBetween(parent, start, end, radius, material, segments = 16) {
  const startPoint = Array.isArray(start) ? worldToThree(start) : start.clone();
  const endPoint = Array.isArray(end) ? worldToThree(end) : end.clone();
  const delta = endPoint.clone().sub(startPoint);
  const length = delta.length();
  if (length < 0.001) {
    return null;
  }

  const geometry = new THREE.CylinderGeometry(radius, radius, length, segments);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(startPoint).add(endPoint).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), delta.normalize());
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function addSphere(parent, centerWorld, radius, material) {
  const geometry = new THREE.SphereGeometry(radius, 24, 16);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.copy(worldToThree(centerWorld));
  mesh.castShadow = true;
  parent.add(mesh);
  return mesh;
}

function lerpWorld(a, b, t) {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];
}

function addWorldOffset(point, offset) {
  return [point[0] + offset[0], point[1] + offset[1], point[2] + offset[2]];
}

function normalizedWorldDirection(start, end) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const dz = end[2] - start[2];
  const length = Math.hypot(dx, dy, dz) || 1;
  return [dx / length, dy / length, dz / length];
}

function horizontalSideVector(direction) {
  const side = [-direction[1], direction[0], 0];
  const length = Math.hypot(side[0], side[1]) || 1;
  return [side[0] / length, side[1] / length, 0];
}

function scaleWorld(vector, scalar) {
  return [vector[0] * scalar, vector[1] * scalar, vector[2] * scalar];
}

function addTruss(parent, start, end, width, height, material) {
  const direction = normalizedWorldDirection(start, end);
  const side = horizontalSideVector(direction);
  const sideOffset = scaleWorld(side, width * 0.5);
  const topOffset = [0, 0, height * 0.5];
  const bottomOffset = [0, 0, -height * 0.35];

  const topLeftStart = addWorldOffset(addWorldOffset(start, sideOffset), topOffset);
  const topLeftEnd = addWorldOffset(addWorldOffset(end, sideOffset), topOffset);
  const topRightStart = addWorldOffset(addWorldOffset(start, scaleWorld(sideOffset, -1)), topOffset);
  const topRightEnd = addWorldOffset(addWorldOffset(end, scaleWorld(sideOffset, -1)), topOffset);
  const bottomStart = addWorldOffset(start, bottomOffset);
  const bottomEnd = addWorldOffset(end, bottomOffset);

  addCylinderBetween(parent, topLeftStart, topLeftEnd, 0.055, material, 10);
  addCylinderBetween(parent, topRightStart, topRightEnd, 0.055, material, 10);
  addCylinderBetween(parent, bottomStart, bottomEnd, 0.07, material, 10);

  const divisions = 8;
  for (let index = 0; index < divisions; index += 1) {
    const a = index / divisions;
    const b = (index + 1) / divisions;
    const top = addWorldOffset(
      addWorldOffset(lerpWorld(start, end, index % 2 === 0 ? a : b), sideOffset),
      topOffset,
    );
    const bottom = addWorldOffset(lerpWorld(start, end, index % 2 === 0 ? b : a), bottomOffset);
    const topOpposite = addWorldOffset(
      addWorldOffset(lerpWorld(start, end, index % 2 === 0 ? a : b), scaleWorld(sideOffset, -1)),
      topOffset,
    );
    addCylinderBetween(parent, top, bottom, 0.035, material, 8);
    addCylinderBetween(parent, topOpposite, bottom, 0.035, material, 8);
  }
}

function setupLights() {
  const hemisphere = new THREE.HemisphereLight(0xffffff, 0x6b7280, 2.8);
  scene.add(hemisphere);

  const key = new THREE.DirectionalLight(0xffffff, 2.8);
  key.position.set(-35, 70, 40);
  key.castShadow = true;
  scene.add(key);

  const fill = new THREE.DirectionalLight(0xffffff, 0.85);
  fill.position.set(55, 32, -45);
  scene.add(fill);
}

function setupStaticScene() {
  clearGroup(staticGroup);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(128, 74), materials.ground);
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(12, -0.03, 4);
  ground.receiveShadow = true;
  staticGroup.add(ground);

  for (const y of [-1.25, 1.25]) {
    addWorldBox(staticGroup, [10, y, 0.13], { x: 94, y: 0.24, z: 0.26 }, materials.rail);
  }
  for (const y of [-2.1, 2.1]) {
    addWorldBox(staticGroup, [10, y, 0.08], { x: 96, y: 0.18, z: 0.16 }, materials.railGuard);
  }
  for (let x = -36; x <= 56; x += 4) {
    addWorldBox(staticGroup, [x, 0, 0.04], { x: 0.24, y: 4.8, z: 0.08 }, materials.rail);
  }
}

function renderVessels(sceneData) {
  clearGroup(vesselsGroup);

  for (const vessel of sceneData.vessels ?? []) {
    const group = new THREE.Group();
    group.name = vessel.id;
    group.position.copy(worldToThree(vessel.position));
    vesselsGroup.add(group);

    const length = vessel.length_m;
    const width = vessel.width_m;
    const height = vessel.height_m;
    addBox(group, new THREE.Vector3(0, 0, 0), new THREE.Vector3(length, height, width), materials.shipHull);
    addBox(
      group,
      new THREE.Vector3(0, height * 0.5 + 0.08, 0),
      new THREE.Vector3(length * 0.88, 0.12, width * 0.86),
      materials.belt,
    );
    addBox(
      group,
      new THREE.Vector3(-length * 0.46, height * 0.62, 0),
      new THREE.Vector3(length * 0.08, height * 0.38, width * 0.9),
      materials.shipTrim,
    );
    addBox(
      group,
      new THREE.Vector3(length * 0.46, height * 0.62, 0),
      new THREE.Vector3(length * 0.08, height * 0.38, width * 0.9),
      materials.shipTrim,
    );

    for (const hold of vessel.holds ?? []) {
      addHold(group, hold, height);
    }
  }
}

function addHold(group, hold, vesselHeight) {
  const x = hold.center_offset_m;
  const top = vesselHeight * 0.5 + 0.22;
  const rimHeight = 0.22;
  const rimWidth = 0.28;
  const length = hold.length_m;
  const width = hold.width_m;
  addBox(group, new THREE.Vector3(x, top, -width * 0.5), new THREE.Vector3(length, rimHeight, rimWidth), materials.holdRim);
  addBox(group, new THREE.Vector3(x, top, width * 0.5), new THREE.Vector3(length, rimHeight, rimWidth), materials.holdRim);
  addBox(group, new THREE.Vector3(x - length * 0.5, top, 0), new THREE.Vector3(rimWidth, rimHeight, width), materials.holdRim);
  addBox(group, new THREE.Vector3(x + length * 0.5, top, 0), new THREE.Vector3(rimWidth, rimHeight, width), materials.holdRim);

  const fillHeight = 0.18 + hold.fill_level * 0.5;
  addBox(
    group,
    new THREE.Vector3(x, vesselHeight * 0.5 + fillHeight * 0.5 + 0.02, 0),
    new THREE.Vector3(length * 0.84, fillHeight, width * 0.76),
    materials.coal,
  );
}

function rebuildLoader(snapshot) {
  clearGroup(loaderGroup);
  const keyPoints = snapshot.key_points;
  const base = keyPoints.base_position;
  const root = keyPoints.boom_root_position;
  const fixedTip = keyPoints.fixed_boom_tip_position;
  const tip = keyPoints.boom_tip_position;
  const chuteBottom = keyPoints.chute_bottom_position;
  const discharge = keyPoints.discharge_point;
  const boomDirection = keyPoints.boom_direction;
  const chuteDirection = keyPoints.chute_direction;

  addWorldBox(loaderGroup, [base[0], base[1], 0.35], { x: 5.8, y: 3.8, z: 0.7 }, materials.loaderDark);
  addWorldBox(loaderGroup, [base[0], base[1], 0.9], { x: 4.8, y: 2.7, z: 0.45 }, materials.loader);

  const legCorners = [
    [-1.55, -1.15],
    [-1.55, 1.15],
    [1.55, -1.15],
    [1.55, 1.15],
  ];
  for (const [xOffset, yOffset] of legCorners) {
    addCylinderBetween(
      loaderGroup,
      [base[0] + xOffset, base[1] + yOffset, 0.75],
      [base[0] + xOffset * 0.42, base[1] + yOffset * 0.42, base[2] + 0.1],
      0.08,
      materials.loader,
      10,
    );
  }

  addWorldBox(loaderGroup, [base[0], base[1], base[2] + 0.08], { x: 3.8, y: 2.8, z: 0.26 }, materials.loader);
  addVerticalCylinder(loaderGroup, [base[0], base[1], base[2] + 0.22], 1.25, 0.42, materials.loader, 36);
  addCylinderBetween(loaderGroup, base, root, 0.12, materials.loader, 12);

  const back = scaleWorld([boomDirection[0], boomDirection[1], 0], -1);
  addWorldBox(
    loaderGroup,
    [base[0] + back[0] * 2.0, base[1] + back[1] * 2.0, base[2] + 0.7],
    { x: 1.8, y: 1.5, z: 1.0 },
    materials.loaderDark,
  );

  addCylinderBetween(loaderGroup, root, fixedTip, 0.18, materials.boom, 14);
  addCylinderBetween(loaderGroup, fixedTip, tip, 0.14, materials.boomDark, 14);
  addCylinderBetween(loaderGroup, addWorldOffset(root, [0, 0, 0.22]), addWorldOffset(tip, [0, 0, 0.22]), 0.055, materials.belt, 10);
  addTruss(loaderGroup, root, fixedTip, 0.82, 0.9, materials.boom);
  addTruss(loaderGroup, fixedTip, tip, 0.58, 0.62, materials.boom);

  addSphere(loaderGroup, tip, 0.28, materials.chuteSleeve);
  addCylinderBetween(loaderGroup, tip, chuteBottom, 0.2, materials.chute, 18);
  addCylinderBetween(
    loaderGroup,
    addWorldOffset(tip, [0, 0, -0.35]),
    addWorldOffset(chuteBottom, [0, 0, 0.25]),
    0.28,
    materials.chuteSleeve,
    18,
  );
  const chuteArrowEnd = [
    discharge[0] + chuteDirection[0] * 1.25,
    discharge[1] + chuteDirection[1] * 1.25,
    discharge[2] - 0.1,
  ];
  addCylinderBetween(loaderGroup, chuteBottom, discharge, 0.14, materials.chuteSleeve, 14);
  addCylinderBetween(loaderGroup, discharge, chuteArrowEnd, 0.1, materials.chute, 12);
  addSphere(loaderGroup, chuteArrowEnd, 0.22, materials.discharge);
}

function updateTrajectory(snapshot) {
  const point = worldToThree(snapshot.key_points.discharge_point);
  trajectoryPoints.push(point);
  if (trajectoryPoints.length > 280) {
    trajectoryPoints = trajectoryPoints.slice(-280);
  }

  if (trajectoryLine) {
    scene.remove(trajectoryLine);
    trajectoryLine.geometry.dispose();
  }

  if (trajectoryPoints.length < 2) {
    return;
  }

  const geometry = new THREE.BufferGeometry().setFromPoints(trajectoryPoints);
  trajectoryLine = new THREE.Line(geometry, materials.trajectory);
  scene.add(trajectoryLine);
}

function renderSnapshot(snapshot) {
  latestSnapshot = snapshot;
  rebuildLoader(snapshot);
  updateTrajectory(snapshot);
  updateReadouts(snapshot);
}

function updateReadouts(snapshot) {
  const axes = snapshot.axis_states;
  simClock.textContent = `t=${format(snapshot.sim_time, 1)}s`;
  stateReadout.innerHTML = "";
  const rows = [
    ["Travel", `${format(axes.travel.current)} m`],
    ["Slew", `${format(axes.slew.current)} deg`],
    ["Luff", `${format(axes.boom_luff.current)} deg`],
    ["Extend", `${format(axes.boom_extension.current)} m`],
    ["Chute", `${format(axes.chute_rotate.current)} deg`],
    ["Belt", `${snapshot.belt_state.running ? "ON" : "OFF"} ${format(snapshot.belt_state.speed_mps, 1)} m/s`],
  ];

  for (const [label, value] of rows) {
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    stateReadout.append(term, description);
  }

  for (const axis of AXES) {
    const state = axes[axis.id];
    const current = document.querySelector(`[data-axis-current="${axis.id}"]`);
    if (current && state) {
      current.textContent = `current ${format(state.current)} ${axis.unit} | target ${format(state.target)} ${axis.unit}`;
    }
  }

  setStatus(
    `ships ${(window.currentScene?.vessels ?? []).length} | discharge ${format(snapshot.key_points.discharge_point[0])}, ${format(snapshot.key_points.discharge_point[1])}, ${format(snapshot.key_points.discharge_point[2])}`,
  );
}

function createAxisControls(snapshot) {
  axisControls.innerHTML = "";
  for (const axis of AXES) {
    const state = snapshot.axis_states[axis.id];
    const container = document.createElement("article");
    container.className = "axis-control";
    container.innerHTML = `
      <h2>${axis.label}</h2>
      <div class="field">
        <label for="${axis.id}-target">Target</label>
        <input id="${axis.id}-target" data-axis-target="${axis.id}" type="number" step="${axis.step}" value="${state.target}">
      </div>
      <div class="field">
        <label for="${axis.id}-velocity">Speed</label>
        <input id="${axis.id}-velocity" data-axis-velocity="${axis.id}" type="number" min="0" step="${axis.step}" value="${state.velocity}">
      </div>
      <button type="button" data-axis-submit="${axis.id}">Set</button>
      <div class="axis-current" data-axis-current="${axis.id}"></div>
    `;
    const targetInput = container.querySelector(`[data-axis-target="${axis.id}"]`);
    if (state.min_value !== null && state.min_value !== undefined) {
      targetInput.min = state.min_value;
    }
    if (state.max_value !== null && state.max_value !== undefined) {
      targetInput.max = state.max_value;
    }
    axisControls.appendChild(container);
  }

  axisControls.addEventListener("click", (event) => {
    const button = event.target.closest("[data-axis-submit]");
    if (!button) {
      return;
    }
    setAxisTarget(button.dataset.axisSubmit).catch((error) => setStatus(`Command rejected: ${error.message}`));
  });
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail ?? text;
    } catch {
      detail = text;
    }
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return response.json();
}

async function setAxisTarget(axisId) {
  const targetInput = document.querySelector(`[data-axis-target="${axisId}"]`);
  const velocityInput = document.querySelector(`[data-axis-velocity="${axisId}"]`);
  const payload = {
    target: Number(targetInput.value),
    velocity: Number(velocityInput.value),
  };
  await requestJson(API.axisTarget(axisId), {
    method: "POST",
    body: JSON.stringify(payload),
  });
  running = true;
  runButton.classList.add("primary");
  pauseButton.classList.remove("primary");
  const snapshot = await requestJson(API.resume, { method: "POST" });
  renderSnapshot(snapshot);
  setStatus(`Applied ${axisId}: target ${format(payload.target)} | running`);
}

async function loadScene() {
  const sceneData = await requestJson(API.scene);
  window.currentScene = sceneData;
  sceneJson.value = JSON.stringify(sceneData, null, 2);
  renderVessels(sceneData);
  return sceneData;
}

async function applySceneJson() {
  const nextScene = JSON.parse(sceneJson.value);
  const sceneData = await requestJson(API.scene, {
    method: "PUT",
    body: JSON.stringify(nextScene),
  });
  window.currentScene = sceneData;
  sceneJson.value = JSON.stringify(sceneData, null, 2);
  renderVessels(sceneData);
  if (latestSnapshot) {
    renderSnapshot(latestSnapshot);
  }
}

async function stepSimulation() {
  if (!running || stepping) {
    return;
  }
  stepping = true;
  try {
    const snapshot = await requestJson(API.step, {
      method: "POST",
      body: JSON.stringify({ dt: 0.1 }),
    });
    renderSnapshot(snapshot);
  } catch (error) {
    setStatus(error.message);
    running = false;
  } finally {
    stepping = false;
  }
}

async function runSimulation() {
  running = true;
  runButton.classList.add("primary");
  pauseButton.classList.remove("primary");
  const snapshot = await requestJson(API.resume, { method: "POST" });
  renderSnapshot(snapshot);
}

async function pauseSimulation() {
  running = false;
  runButton.classList.remove("primary");
  pauseButton.classList.add("primary");
  const snapshot = await requestJson(API.pause, { method: "POST" });
  renderSnapshot(snapshot);
}

async function resetSimulation() {
  running = false;
  runButton.classList.remove("primary");
  pauseButton.classList.remove("primary");
  trajectoryPoints = [];
  if (trajectoryLine) {
    scene.remove(trajectoryLine);
    trajectoryLine.geometry.dispose();
    trajectoryLine = null;
  }
  const snapshot = await requestJson(API.reset, { method: "POST" });
  renderSnapshot(snapshot);
}

function resizeRenderer() {
  const rect = sceneRoot.getBoundingClientRect();
  renderer.setSize(Math.max(1, rect.width), Math.max(1, rect.height), false);
  camera.aspect = Math.max(1, rect.width) / Math.max(1, rect.height);
  camera.updateProjectionMatrix();
}

function renderLoop() {
  controls.update();
  renderer.render(scene, camera);
}

async function init() {
  renderer.shadowMap.enabled = true;
  setupLights();
  setupStaticScene();
  resizeRenderer();

  const resizeObserver = new ResizeObserver(resizeRenderer);
  resizeObserver.observe(sceneRoot);

  runButton.classList.add("primary");
  runButton.addEventListener("click", () => runSimulation().catch((error) => setStatus(error.message)));
  pauseButton.addEventListener("click", () => pauseSimulation().catch((error) => setStatus(error.message)));
  resetButton.addEventListener("click", () => resetSimulation().catch((error) => setStatus(error.message)));
  applySceneButton.addEventListener("click", () => applySceneJson().catch((error) => setStatus(error.message)));

  await loadScene();
  const snapshot = await requestJson(API.state);
  createAxisControls(snapshot);
  renderSnapshot(snapshot);

  renderer.setAnimationLoop(renderLoop);
  tickTimer = window.setInterval(stepSimulation, 100);
}

window.addEventListener("beforeunload", () => {
  if (tickTimer) {
    window.clearInterval(tickTimer);
  }
});

init().catch((error) => {
  setStatus(error.message);
});
