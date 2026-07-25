import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { worldToThree } from "./shiploader/coordinate-frame.js";
import { ProceduralShiploaderRig } from "./shiploader/procedural-rig.js?v=sl15-procedural-r4";

const API = {
  loaderConfig: "/api/loader/config",
  state: "/api/state",
  scene: "/api/scene",
  step: "/api/simulation/step",
  pause: "/api/simulation/pause",
  resume: "/api/simulation/resume",
  reset: "/api/simulation/reset",
  axisTarget: (axisId) => `/api/axis/${axisId}/target`,
};

const AXES = [
  { id: "travel", label: "大车行走", unit: "m", step: "0.1" },
  { id: "slew", label: "臂架回转", unit: "deg", step: "0.1" },
  { id: "boom_luff", label: "臂架俯仰", unit: "deg", step: "0.1" },
  { id: "boom_extension", label: "臂架伸缩", unit: "m", step: "0.1" },
  { id: "chute_rotate", label: "溜筒回转", unit: "deg", step: "1" },
];

const sceneRoot = document.querySelector("#scene-root");
const viewStatus = document.querySelector("#view-status");
const simClock = document.querySelector("#sim-clock");
const axisControls = document.querySelector("#axis-controls");
const stateReadout = document.querySelector("#state-readout");
const sceneJson = document.querySelector("#scene-json");
const coverControls = document.querySelector("#cover-controls");
const runButton = document.querySelector("#run-button");
const pauseButton = document.querySelector("#pause-button");
const resetButton = document.querySelector("#reset-button");
const applySceneButton = document.querySelector("#apply-scene-button");
const applyCoversButton = document.querySelector("#apply-covers-button");
const modelBadge = document.querySelector("#model-badge");
const viewButtons = document.querySelector("#view-buttons");

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xd6dee5);
scene.fog = new THREE.Fog(0xd6dee5, 95, 170);

const perspectiveCamera = new THREE.PerspectiveCamera(42, 1, 0.1, 1000);
perspectiveCamera.position.set(58, 44, 68);
const orthographicCamera = new THREE.OrthographicCamera(-50, 50, 35, -35, 0.1, 1000);
let activeCamera = perspectiveCamera;

const renderer = new THREE.WebGLRenderer({
  antialias: true,
  alpha: false,
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
sceneRoot.appendChild(renderer.domElement);

const controls = new OrbitControls(activeCamera, renderer.domElement);
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
  belt: new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.7 }),
  shipHull: new THREE.MeshStandardMaterial({ color: 0x121826, roughness: 0.64 }),
  shipTrim: new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.5 }),
  holdRim: new THREE.MeshStandardMaterial({ color: 0x1f2937, roughness: 0.62 }),
  coal: new THREE.MeshStandardMaterial({ color: 0x050505, roughness: 0.95 }),
  coverHorizontal: new THREE.MeshStandardMaterial({ color: 0xc8d2dc, roughness: 0.5, metalness: 0.08 }),
  coverVertical: new THREE.MeshStandardMaterial({ color: 0xe6edf3, roughness: 0.48, metalness: 0.08 }),
  coverEdge: new THREE.MeshStandardMaterial({ color: 0x64748b, roughness: 0.5, metalness: 0.05 }),
  trajectory: new THREE.LineBasicMaterial({ color: 0x16a34a }),
};

const staticGroup = new THREE.Group();
const vesselsGroup = new THREE.Group();
const loaderGroup = new THREE.Group();
scene.add(staticGroup, vesselsGroup, loaderGroup);

let trajectoryLine = null;
let trajectoryGeometry = null;
let trajectoryAttribute = null;
let trajectoryCount = 0;
const trajectoryCapacity = 280;
let latestSnapshot = null;
let loaderConfig = null;
let shiploaderRig = null;
let running = true;
let stepping = false;
let tickTimer = null;

function setStatus(message) {
  viewStatus.textContent = message;
}

function format(value, digits = 2) {
  if (!Number.isFinite(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function formatLimit(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "不限";
  }
  return String(Number(value));
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

function setupStaticScene(config) {
  clearGroup(staticGroup);

  const ground = new THREE.Mesh(new THREE.PlaneGeometry(150, 86), materials.ground);
  ground.rotation.x = -Math.PI / 2;
  ground.position.set(10, -0.03, 3);
  ground.receiveShadow = true;
  staticGroup.add(ground);

  const halfGauge = config.engineering.rail_gauge_m * 0.5;
  for (const y of [-halfGauge, halfGauge]) {
    addWorldBox(staticGroup, [10, y, 0.18], { x: 118, y: 0.32, z: 0.36 }, materials.rail);
  }
  for (const y of [-halfGauge - 1.15, halfGauge + 1.15]) {
    addWorldBox(staticGroup, [10, y, 0.1], { x: 120, y: 0.16, z: 0.2 }, materials.railGuard);
  }
  for (let x = -48; x <= 68; x += 2.5) {
    addWorldBox(
      staticGroup,
      [x, 0, 0.07],
      { x: 0.28, y: config.engineering.rail_gauge_m + 2.8, z: 0.14 },
      materials.rail,
    );
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
      addHatchCover(group, hold, vessel.cover_type, height);
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

function addHatchCover(group, hold, coverType, vesselHeight) {
  if (!coverType || coverType === "none") {
    return;
  }

  const cover = hold.cover ?? {};
  const thickness = cover.thickness_m ?? 0.2;
  const top = vesselHeight * 0.5 + 0.42;
  const x = hold.center_offset_m;

  if (coverType === "horizontal") {
    const length = cover.length_m ?? hold.length_m * 0.92;
    const width = cover.width_m ?? hold.width_m * 0.36;
    for (const side of [-1, 1]) {
      const z = side * (hold.width_m * 0.5 + width * 0.5 + 0.42);
      addBox(
        group,
        new THREE.Vector3(x, top + thickness * 0.5, z),
        new THREE.Vector3(length, thickness, width),
        materials.coverHorizontal,
      );
      addBox(
        group,
        new THREE.Vector3(x, top + thickness + 0.03, z),
        new THREE.Vector3(length * 0.96, 0.05, 0.08),
        materials.coverEdge,
      );
    }
    return;
  }

  if (coverType === "vertical") {
    const height = cover.length_m ?? Math.min(2.4, hold.length_m * 0.35);
    const width = cover.width_m ?? hold.width_m * 0.9;
    for (const end of [-1, 1]) {
      const xEnd = x + end * (hold.length_m * 0.5 + thickness * 0.5 + 0.36);
      addBox(
        group,
        new THREE.Vector3(xEnd, top + height * 0.5, 0),
        new THREE.Vector3(thickness, height, width),
        materials.coverVertical,
      );
      addBox(
        group,
        new THREE.Vector3(xEnd + end * thickness * 0.55, top + height * 0.5, 0),
        new THREE.Vector3(0.06, height * 0.9, width * 0.92),
        materials.coverEdge,
      );
    }
  }
}

function setupTrajectory() {
  trajectoryGeometry = new THREE.BufferGeometry();
  trajectoryAttribute = new THREE.BufferAttribute(
    new Float32Array(trajectoryCapacity * 3),
    3,
  );
  trajectoryAttribute.setUsage(THREE.DynamicDrawUsage);
  trajectoryGeometry.setAttribute("position", trajectoryAttribute);
  trajectoryGeometry.setDrawRange(0, 0);
  trajectoryLine = new THREE.Line(trajectoryGeometry, materials.trajectory);
  trajectoryLine.frustumCulled = false;
  scene.add(trajectoryLine);
}

function updateTrajectory(snapshot) {
  const point = worldToThree(snapshot.key_points.discharge_point);
  const values = trajectoryAttribute.array;
  if (trajectoryCount >= trajectoryCapacity) {
    values.copyWithin(0, 3);
    trajectoryCount = trajectoryCapacity - 1;
  }
  trajectoryAttribute.setXYZ(trajectoryCount, point.x, point.y, point.z);
  trajectoryCount += 1;
  trajectoryAttribute.needsUpdate = true;
  trajectoryGeometry.setDrawRange(0, trajectoryCount);
}

function renderSnapshot(snapshot) {
  latestSnapshot = snapshot;
  shiploaderRig.update(snapshot);
  updateTrajectory(snapshot);
  updateReadouts(snapshot);
  window.__shiploaderDiagnostics = {
    ...shiploaderRig.getDiagnostics(),
    rendererCalls: renderer.info.render.calls,
    rendererTriangles: renderer.info.render.triangles,
    rendererGeometries: renderer.info.memory.geometries,
    rendererTextures: renderer.info.memory.textures,
  };
}

function updateReadouts(snapshot) {
  const axes = snapshot.axis_states;
  simClock.textContent = `t=${format(snapshot.sim_time, 1)}s`;
  stateReadout.innerHTML = "";
  const rows = [
    ["方案", loaderConfig.variant_id],
    ["大车", `${format(axes.travel.current)} m`],
    ["回转", `${format(axes.slew.current)}°`],
    ["俯仰", `${format(axes.boom_luff.current)}°`],
    ["伸缩", `${format(axes.boom_extension.current)} m`],
    ["溜筒", `${format(axes.chute_rotate.current)}°`],
    ["皮带", `${snapshot.belt_state.running ? "运行" : "停止"} ${format(snapshot.belt_state.speed_mps, 1)} m/s`],
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
      current.textContent = `当前 ${format(state.current)} ${axis.unit} · 目标 ${format(state.target)} ${axis.unit}`;
    }
  }

  const diagnostics = shiploaderRig.getDiagnostics();
  setStatus(
    `${loaderConfig.variant_id} · 23 m 轨距 · 伸缩 21.25 m · 关键点误差 ${format(diagnostics.maxKeypointErrorM, 4)} m`,
  );
}

function createAxisControls(snapshot) {
  axisControls.innerHTML = `
    <p class="axis-help">
      范围说明：目标为机械行程上下限；速度为 0 到最大允许值。
    </p>
  `;
  for (const axis of AXES) {
    const state = snapshot.axis_states[axis.id];
    const velocityUnit = axis.unit === "m" ? "m/s" : "deg/s";
    const targetLimitId = `${axis.id}-target-limit`;
    const velocityLimitId = `${axis.id}-velocity-limit`;
    const container = document.createElement("article");
    container.className = "axis-control";
    container.innerHTML = `
      <h2>${axis.label}</h2>
      <div class="field">
        <label for="${axis.id}-target">目标</label>
        <input id="${axis.id}-target" data-axis-target="${axis.id}" type="number" step="${axis.step}" value="${state.target}" aria-describedby="${targetLimitId}" required>
      </div>
      <div class="field">
        <label for="${axis.id}-velocity">速度</label>
        <input id="${axis.id}-velocity" data-axis-velocity="${axis.id}" type="number" min="0" step="${axis.step}" value="${state.velocity}" aria-describedby="${velocityLimitId}" required>
      </div>
      <button type="button" data-axis-submit="${axis.id}">设置</button>
      <div class="axis-limits">
        <span id="${targetLimitId}">目标范围 ${formatLimit(state.min_value)} ～ ${formatLimit(state.max_value)} ${axis.unit}</span>
        <span id="${velocityLimitId}">速度范围 0 ～ ${formatLimit(state.max_velocity)} ${velocityUnit}</span>
      </div>
      <div class="axis-current" data-axis-current="${axis.id}"></div>
    `;
    const targetInput = container.querySelector(`[data-axis-target="${axis.id}"]`);
    if (state.min_value !== null && state.min_value !== undefined) {
      targetInput.min = state.min_value;
    }
    if (state.max_value !== null && state.max_value !== undefined) {
      targetInput.max = state.max_value;
    }
    const velocityInput = container.querySelector(`[data-axis-velocity="${axis.id}"]`);
    if (state.max_velocity !== null && state.max_velocity !== undefined) {
      velocityInput.max = state.max_velocity;
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

function renderCoverControls(sceneData) {
  coverControls.innerHTML = "";
  for (const [vesselIndex, vessel] of (sceneData.vessels ?? []).entries()) {
    const vesselSection = document.createElement("article");
    vesselSection.className = "cover-vessel";
    vesselSection.innerHTML = `
      <div class="cover-vessel-title">
        <h3>${vessel.id}</h3>
        <select data-cover-type="${vesselIndex}" aria-label="${vessel.id} cover type">
          <option value="none">No cover</option>
          <option value="horizontal">Horizontal</option>
          <option value="vertical">Vertical</option>
        </select>
      </div>
    `;
    const typeSelect = vesselSection.querySelector(`[data-cover-type="${vesselIndex}"]`);
    typeSelect.value = vessel.cover_type ?? "none";

    for (const [holdIndex, hold] of (vessel.holds ?? []).entries()) {
      const cover = hold.cover ?? {};
      const row = document.createElement("div");
      row.className = "cover-hold";
      row.innerHTML = `
        <strong>${hold.id}</strong>
        <input data-cover-length="${vesselIndex}:${holdIndex}" type="number" min="0" step="0.1" placeholder="Len or height" title="Horizontal: each side cover length. Vertical: each end cover height." value="${cover.length_m ?? ""}">
        <input data-cover-width="${vesselIndex}:${holdIndex}" type="number" min="0" step="0.1" placeholder="Pair width" title="One value is used for both side/end covers." value="${cover.width_m ?? ""}">
        <input data-cover-thickness="${vesselIndex}:${holdIndex}" type="number" min="0" step="0.01" placeholder="Thick" title="One value is used for both side/end covers." value="${cover.thickness_m ?? ""}">
      `;
      vesselSection.appendChild(row);
    }

    coverControls.appendChild(vesselSection);
  }
}

function readOptionalNumber(input, label) {
  const raw = input.value.trim();
  if (raw === "") {
    return null;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label} must be a positive number`);
  }
  return value;
}

async function applyCoverControls() {
  const nextScene = JSON.parse(JSON.stringify(window.currentScene));
  for (const [vesselIndex, vessel] of (nextScene.vessels ?? []).entries()) {
    const typeSelect = document.querySelector(`[data-cover-type="${vesselIndex}"]`);
    vessel.cover_type = typeSelect?.value ?? "none";
    for (const [holdIndex, hold] of (vessel.holds ?? []).entries()) {
      const key = `${vesselIndex}:${holdIndex}`;
      const length = readOptionalNumber(document.querySelector(`[data-cover-length="${key}"]`), `${hold.id} cover length`);
      const width = readOptionalNumber(document.querySelector(`[data-cover-width="${key}"]`), `${hold.id} cover width`);
      const thickness = readOptionalNumber(
        document.querySelector(`[data-cover-thickness="${key}"]`),
        `${hold.id} cover thickness`,
      );
      const cover = {};
      if (length !== null) {
        cover.length_m = length;
      }
      if (width !== null) {
        cover.width_m = width;
      }
      if (thickness !== null) {
        cover.thickness_m = thickness;
      }
      if (Object.keys(cover).length > 0) {
        hold.cover = cover;
      } else {
        delete hold.cover;
      }
    }
  }

  const sceneData = await requestJson(API.scene, {
    method: "PUT",
    body: JSON.stringify(nextScene),
  });
  window.currentScene = sceneData;
  sceneJson.value = JSON.stringify(sceneData, null, 2);
  renderVessels(sceneData);
  renderCoverControls(sceneData);
  if (latestSnapshot) {
    renderSnapshot(latestSnapshot);
  }
  setStatus("Hatch cover settings applied");
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
  if (!targetInput.checkValidity()) {
    targetInput.reportValidity();
    throw new Error("目标值超出允许范围");
  }
  if (!velocityInput.checkValidity()) {
    velocityInput.reportValidity();
    throw new Error("速度值超出允许范围");
  }
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
  renderCoverControls(sceneData);
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
  renderCoverControls(sceneData);
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
  trajectoryCount = 0;
  trajectoryGeometry.setDrawRange(0, 0);
  const snapshot = await requestJson(API.reset, { method: "POST" });
  renderSnapshot(snapshot);
}

function resizeRenderer() {
  const rect = sceneRoot.getBoundingClientRect();
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  const aspect = width / height;
  renderer.setSize(width, height, false);
  perspectiveCamera.aspect = aspect;
  perspectiveCamera.updateProjectionMatrix();
  const halfHeight = 35;
  orthographicCamera.left = -halfHeight * aspect;
  orthographicCamera.right = halfHeight * aspect;
  orthographicCamera.top = halfHeight;
  orthographicCamera.bottom = -halfHeight;
  orthographicCamera.updateProjectionMatrix();
}

function renderLoop() {
  controls.update();
  renderer.render(scene, activeCamera);
}

function cameraTarget() {
  if (!latestSnapshot) {
    return new THREE.Vector3(0, 11, 6);
  }
  const base = worldToThree(latestSnapshot.key_points.base_position);
  return new THREE.Vector3(base.x, loaderConfig.geometry.base_height_m * 0.75, base.z + 6);
}

function setCameraPreset(preset) {
  const target = cameraTarget();
  if (preset === "perspective") {
    activeCamera = perspectiveCamera;
    activeCamera.up.set(0, 1, 0);
    activeCamera.position.copy(target).add(new THREE.Vector3(48, 34, 54));
    controls.enableRotate = true;
  } else {
    activeCamera = orthographicCamera;
    controls.enableRotate = false;
    if (preset === "front") {
      activeCamera.up.set(0, 1, 0);
      activeCamera.position.copy(target).add(new THREE.Vector3(90, 0, 0));
    } else if (preset === "side") {
      activeCamera.up.set(0, 1, 0);
      activeCamera.position.copy(target).add(new THREE.Vector3(0, 0, 90));
    } else {
      activeCamera.up.set(0, 0, -1);
      activeCamera.position.copy(target).add(new THREE.Vector3(0, 100, 0));
    }
  }
  controls.object = activeCamera;
  controls.target.copy(target);
  controls.update();
  resizeRenderer();
  for (const button of viewButtons.querySelectorAll("[data-view]")) {
    button.classList.toggle("primary", button.dataset.view === preset);
    button.setAttribute("aria-pressed", button.dataset.view === preset ? "true" : "false");
  }
}

async function init() {
  window.__shiploaderReady = false;
  renderer.shadowMap.enabled = true;
  setupLights();
  loaderConfig = await requestJson(API.loaderConfig);
  modelBadge.textContent = `${loaderConfig.variant_id} · ${format(loaderConfig.engineering.rated_capacity_tph, 0)} t/h`;
  setupStaticScene(loaderConfig);
  setupTrajectory();
  shiploaderRig = new ProceduralShiploaderRig(loaderConfig);
  loaderGroup.add(shiploaderRig.root);
  resizeRenderer();

  const resizeObserver = new ResizeObserver(resizeRenderer);
  resizeObserver.observe(sceneRoot);

  runButton.classList.add("primary");
  runButton.addEventListener("click", () => runSimulation().catch((error) => setStatus(error.message)));
  pauseButton.addEventListener("click", () => pauseSimulation().catch((error) => setStatus(error.message)));
  resetButton.addEventListener("click", () => resetSimulation().catch((error) => setStatus(error.message)));
  applySceneButton.addEventListener("click", () => applySceneJson().catch((error) => setStatus(error.message)));
  applyCoversButton.addEventListener("click", () => applyCoverControls().catch((error) => setStatus(error.message)));
  viewButtons.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (button) {
      setCameraPreset(button.dataset.view);
    }
  });

  await loadScene();
  const snapshot = await requestJson(API.state);
  createAxisControls(snapshot);
  renderSnapshot(snapshot);
  setCameraPreset("perspective");
  renderer.compile(scene, activeCamera);

  renderer.setAnimationLoop(renderLoop);
  tickTimer = window.setInterval(stepSimulation, 100);
  window.__shiploaderReady = true;
}

window.addEventListener("beforeunload", () => {
  if (tickTimer) {
    window.clearInterval(tickTimer);
  }
});

init().catch((error) => {
  setStatus(error.message);
});
