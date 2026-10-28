import * as THREE from "three";

import {
  worldLuffToThreeRadians,
  worldToThree,
  worldYawToThreeRadians,
} from "./coordinate-frame.js";

const UP = new THREE.Vector3(0, 1, 0);
const FORWARD = new THREE.Vector3(0, 0, 1);
const RIGHT = new THREE.Vector3(1, 0, 0);
const beamPosition = new THREE.Vector3();
const beamDirection = new THREE.Vector3();
const beamQuaternion = new THREE.Quaternion();
const beamScale = new THREE.Vector3();
const beamMatrix = new THREE.Matrix4();
const shapeDirection = new THREE.Vector3();
const shapePosition = new THREE.Vector3();
const shapeQuaternion = new THREE.Quaternion();
const shapeScale = new THREE.Vector3();
const shapeMatrix = new THREE.Matrix4();

function createPalette() {
  return {
    structure: new THREE.MeshStandardMaterial({
      color: 0xe7a72a,
      roughness: 0.52,
      metalness: 0.18,
    }),
    structureDark: new THREE.MeshStandardMaterial({
      color: 0x6e7780,
      roughness: 0.58,
      metalness: 0.25,
    }),
    structureLight: new THREE.MeshStandardMaterial({
      color: 0xe9edf0,
      roughness: 0.56,
      metalness: 0.14,
    }),
    safety: new THREE.MeshStandardMaterial({
      color: 0xf4c430,
      roughness: 0.46,
      metalness: 0.12,
    }),
    machinery: new THREE.MeshStandardMaterial({
      color: 0x35414b,
      roughness: 0.48,
      metalness: 0.28,
    }),
    belt: new THREE.MeshStandardMaterial({
      color: 0x15191d,
      roughness: 0.86,
      metalness: 0.02,
    }),
    chute: new THREE.MeshStandardMaterial({
      color: 0x3f5f73,
      roughness: 0.5,
      metalness: 0.22,
    }),
    chuteSleeve: new THREE.MeshStandardMaterial({
      color: 0xc9d2d8,
      roughness: 0.48,
      metalness: 0.28,
    }),
    wheel: new THREE.MeshStandardMaterial({
      color: 0x1e2429,
      roughness: 0.7,
      metalness: 0.32,
    }),
    glass: new THREE.MeshPhysicalMaterial({
      color: 0x93c9d8,
      roughness: 0.16,
      metalness: 0,
      transparent: true,
      opacity: 0.72,
    }),
    marker: new THREE.MeshBasicMaterial({ color: 0x00ff88 }),
  };
}

function markMesh(mesh) {
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function setBeamTransform(handle, start, end, thickness) {
  beamDirection.copy(end).sub(start);
  const length = Math.max(beamDirection.length(), 1e-6);
  beamPosition.copy(start).add(end).multiplyScalar(0.5);
  beamQuaternion.setFromUnitVectors(FORWARD, beamDirection.multiplyScalar(1 / length));
  beamScale.set(thickness, thickness, length);
  beamMatrix.compose(beamPosition, beamQuaternion, beamScale);
  handle.pool.setMatrixAt(handle.index, beamMatrix);
  handle.pool.instanceMatrix.needsUpdate = true;
}

function addBeam(parent, geometry, start, end, thickness, material, name = "") {
  parent.userData.beamPools ??= new Map();
  const poolKey = material.uuid;
  let pool = parent.userData.beamPools.get(poolKey);
  if (!pool) {
    pool = new THREE.InstancedMesh(geometry, material, 512);
    pool.name = `${parent.name || "Assembly"}_BeamBatch`;
    pool.count = 0;
    pool.castShadow = true;
    pool.receiveShadow = true;
    pool.frustumCulled = false;
    parent.userData.beamPools.set(poolKey, pool);
    parent.add(pool);
  }
  if (pool.count >= pool.instanceMatrix.count) {
    throw new Error(`Beam batch capacity exceeded in ${parent.name || "assembly"}`);
  }
  const handle = {
    pool,
    index: pool.count,
    name,
    userData: {},
  };
  pool.count += 1;
  setBeamTransform(handle, start, end, thickness);
  return handle;
}

function addCylinderBetween(parent, geometry, start, end, radius, material, name = "") {
  const mesh = markMesh(new THREE.Mesh(geometry, material));
  mesh.name = name;
  setCylinderTransform(mesh, start, end, radius);
  parent.add(mesh);
  return mesh;
}

function setCylinderTransform(mesh, start, end, radius) {
  beamDirection.copy(end).sub(start);
  const length = Math.max(beamDirection.length(), 1e-6);
  mesh.position.copy(start).add(end).multiplyScalar(0.5);
  mesh.quaternion.setFromUnitVectors(UP, beamDirection.multiplyScalar(1 / length));
  mesh.scale.set(radius, length, radius);
}

function addBox(parent, geometry, position, size, material, name = "") {
  const mesh = markMesh(new THREE.Mesh(geometry, material));
  mesh.name = name;
  mesh.position.copy(position);
  mesh.scale.copy(size);
  parent.add(mesh);
  return mesh;
}

function addCylinderY(parent, geometry, position, radius, height, material, name = "") {
  const mesh = markMesh(new THREE.Mesh(geometry, material));
  mesh.name = name;
  mesh.position.copy(position);
  mesh.scale.set(radius, height, radius);
  parent.add(mesh);
  return mesh;
}

function addShapeInstance(
  parent,
  geometry,
  material,
  position,
  quaternion,
  scale,
  name = "",
) {
  parent.userData.shapePools ??= new Map();
  const poolKey = `${geometry.uuid}:${material.uuid}`;
  let pool = parent.userData.shapePools.get(poolKey);
  if (!pool) {
    pool = new THREE.InstancedMesh(geometry, material, 256);
    pool.name = `${parent.name || "Assembly"}_ShapeBatch`;
    pool.count = 0;
    pool.castShadow = true;
    pool.receiveShadow = true;
    pool.frustumCulled = false;
    parent.userData.shapePools.set(poolKey, pool);
    parent.add(pool);
  }
  if (pool.count >= pool.instanceMatrix.count) {
    throw new Error(`Shape batch capacity exceeded in ${parent.name || "assembly"}`);
  }
  shapeMatrix.compose(position, quaternion, scale);
  pool.setMatrixAt(pool.count, shapeMatrix);
  pool.count += 1;
  pool.instanceMatrix.needsUpdate = true;
  return { pool, index: pool.count - 1, name };
}

function addBoxInstance(parent, geometry, position, size, material, name = "") {
  return addShapeInstance(
    parent,
    geometry,
    material,
    position,
    new THREE.Quaternion(),
    size,
    name,
  );
}

function addCylinderYInstance(
  parent,
  geometry,
  position,
  radius,
  height,
  material,
  name = "",
) {
  return addShapeInstance(
    parent,
    geometry,
    material,
    position,
    new THREE.Quaternion(),
    new THREE.Vector3(radius, height, radius),
    name,
  );
}

function addTaperedDuctBetween(
  parent,
  geometry,
  start,
  end,
  width,
  depth,
  material,
  name = "",
) {
  shapeDirection.copy(end).sub(start);
  const length = Math.max(shapeDirection.length(), 1e-6);
  shapePosition.copy(start).add(end).multiplyScalar(0.5);
  shapeQuaternion.setFromUnitVectors(UP, shapeDirection.multiplyScalar(1 / length));
  shapeScale.set(width, length, depth);
  return addShapeInstance(
    parent,
    geometry,
    material,
    shapePosition,
    shapeQuaternion,
    shapeScale,
    name,
  );
}

function addMarker(parent, name, position = new THREE.Vector3()) {
  const marker = new THREE.Object3D();
  marker.name = name;
  marker.position.copy(position);
  parent.add(marker);
  return marker;
}

function createStaticTruss(parent, resources, options) {
  const {
    length,
    width,
    height,
    panels,
    material,
    name,
    beltMaterial,
    rollerMaterial,
  } = options;
  const group = new THREE.Group();
  group.name = name;
  parent.add(group);

  const halfWidth = width * 0.5;
  const halfHeight = height * 0.5;
  for (const x of [-halfWidth, halfWidth]) {
    for (const y of [-halfHeight, halfHeight]) {
      addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(x, y, 0),
        new THREE.Vector3(x, y, length),
        0.16,
        material,
      );
    }
  }

  for (let index = 0; index <= panels; index += 1) {
    const z = (length * index) / panels;
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(-halfWidth, halfHeight, z),
      new THREE.Vector3(halfWidth, halfHeight, z),
      0.11,
      material,
    );
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(-halfWidth, -halfHeight, z),
      new THREE.Vector3(halfWidth, -halfHeight, z),
      0.11,
      material,
    );
  }

  for (let index = 0; index < panels; index += 1) {
    const z0 = (length * index) / panels;
    const z1 = (length * (index + 1)) / panels;
    for (const x of [-halfWidth, halfWidth]) {
      const startY = index % 2 === 0 ? -halfHeight : halfHeight;
      const endY = -startY;
      addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(x, startY, z0),
        new THREE.Vector3(x, endY, z1),
        0.1,
        material,
      );
    }
    const startX = index % 2 === 0 ? -halfWidth : halfWidth;
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(startX, halfHeight, z0),
      new THREE.Vector3(-startX, halfHeight, z1),
      0.08,
      material,
    );
  }

  addBox(
    group,
    resources.unitBox,
    new THREE.Vector3(0, -halfHeight + 0.28, length * 0.5),
    new THREE.Vector3(width * 0.72, 0.1, length),
    beltMaterial,
    `${name}_Belt`,
  );

  const rollers = new THREE.InstancedMesh(resources.roller, rollerMaterial, panels + 1);
  rollers.name = `${name}_Rollers`;
  rollers.castShadow = true;
  const rollerRotation = new THREE.Quaternion().setFromAxisAngle(FORWARD, Math.PI / 2);
  const matrix = new THREE.Matrix4();
  for (let index = 0; index <= panels; index += 1) {
    matrix.compose(
      new THREE.Vector3(0, -halfHeight + 0.42, (length * index) / panels),
      rollerRotation,
      new THREE.Vector3(1, 1, 1),
    );
    rollers.setMatrixAt(index, matrix);
  }
  rollers.instanceMatrix.needsUpdate = true;
  group.add(rollers);
  return group;
}

function createAdjustableTruss(parent, resources, options) {
  const { width, height, panels, material, name, beltMaterial, rollerMaterial } = options;
  const group = new THREE.Group();
  group.name = name;
  parent.add(group);

  const halfWidth = width * 0.5;
  const halfHeight = height * 0.5;
  const chords = [];
  const frames = [];
  const sideDiagonals = [];
  const topDiagonals = [];

  for (const x of [-halfWidth, halfWidth]) {
    for (const y of [-halfHeight, halfHeight]) {
      chords.push(addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(),
        new THREE.Vector3(0, 0, 1),
        0.13,
        material,
      ));
      chords[chords.length - 1].userData.anchor = { x, y };
    }
  }

  for (let index = 0; index <= panels; index += 1) {
    const top = addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(),
      new THREE.Vector3(1, 0, 0),
      0.09,
      material,
    );
    const bottom = addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(),
      new THREE.Vector3(1, 0, 0),
      0.09,
      material,
    );
    frames.push({ top, bottom, index });
  }

  for (let index = 0; index < panels; index += 1) {
    for (const x of [-halfWidth, halfWidth]) {
      sideDiagonals.push({
        mesh: addBeam(
          group,
          resources.unitBox,
          new THREE.Vector3(),
          new THREE.Vector3(0, 1, 1),
          0.08,
          material,
        ),
        x,
        index,
      });
    }
    topDiagonals.push({
      mesh: addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(),
        new THREE.Vector3(1, 0, 1),
        0.07,
        material,
      ),
      index,
    });
  }

  const belt = addBox(
    group,
    resources.unitBox,
    new THREE.Vector3(),
    new THREE.Vector3(1, 1, 1),
    beltMaterial,
    `${name}_Belt`,
  );
  const rollers = new THREE.InstancedMesh(resources.roller, rollerMaterial, panels + 1);
  rollers.name = `${name}_Rollers`;
  rollers.castShadow = true;
  group.add(rollers);

  function setLength(length) {
    for (const chord of chords) {
      const { x, y } = chord.userData.anchor;
      setBeamTransform(
        chord,
        new THREE.Vector3(x, y, 0),
        new THREE.Vector3(x, y, length),
        0.13,
      );
    }
    for (const { top, bottom, index } of frames) {
      const z = (length * index) / panels;
      setBeamTransform(
        top,
        new THREE.Vector3(-halfWidth, halfHeight, z),
        new THREE.Vector3(halfWidth, halfHeight, z),
        0.09,
      );
      setBeamTransform(
        bottom,
        new THREE.Vector3(-halfWidth, -halfHeight, z),
        new THREE.Vector3(halfWidth, -halfHeight, z),
        0.09,
      );
    }
    for (const { mesh, x, index } of sideDiagonals) {
      const z0 = (length * index) / panels;
      const z1 = (length * (index + 1)) / panels;
      const startY = index % 2 === 0 ? -halfHeight : halfHeight;
      setBeamTransform(
        mesh,
        new THREE.Vector3(x, startY, z0),
        new THREE.Vector3(x, -startY, z1),
        0.08,
      );
    }
    for (const { mesh, index } of topDiagonals) {
      const z0 = (length * index) / panels;
      const z1 = (length * (index + 1)) / panels;
      const startX = index % 2 === 0 ? -halfWidth : halfWidth;
      setBeamTransform(
        mesh,
        new THREE.Vector3(startX, halfHeight, z0),
        new THREE.Vector3(-startX, halfHeight, z1),
        0.07,
      );
    }
    belt.position.set(0, -halfHeight + 0.24, length * 0.5);
    belt.scale.set(width * 0.68, 0.09, length);

    const rollerRotation = new THREE.Quaternion().setFromAxisAngle(FORWARD, Math.PI / 2);
    const matrix = new THREE.Matrix4();
    for (let index = 0; index <= panels; index += 1) {
      matrix.compose(
        new THREE.Vector3(0, -halfHeight + 0.38, (length * index) / panels),
        rollerRotation,
        new THREE.Vector3(0.82, 0.82, 0.82),
      );
      rollers.setMatrixAt(index, matrix);
    }
    rollers.instanceMatrix.needsUpdate = true;
  }

  return { group, setLength };
}

function createBogie(parent, resources, palette, position, name) {
  const group = new THREE.Group();
  group.name = name;
  group.position.copy(position);
  parent.add(group);

  addBoxInstance(
    parent,
    resources.unitBox,
    new THREE.Vector3(position.x, 0.72, position.z),
    new THREE.Vector3(5.4, 0.55, 1.6),
    palette.structureDark,
    `${name}_MainFrame`,
  );
  addBoxInstance(
    parent,
    resources.unitBox,
    new THREE.Vector3(position.x, 1.25, position.z),
    new THREE.Vector3(2.8, 0.55, 1.25),
    palette.structure,
    `${name}_RockerFrame`,
  );

  const wheelPositions = [-2.25, -1.35, -0.45, 0.45, 1.35, 2.25];
  const wheelRotation = new THREE.Quaternion().setFromAxisAngle(RIGHT, Math.PI / 2);
  for (const wheelX of wheelPositions) {
    addShapeInstance(
      parent,
      resources.wheel,
      palette.wheel,
      new THREE.Vector3(position.x + wheelX, 0.42, position.z),
      wheelRotation,
      new THREE.Vector3(1, 1, 1),
      `${name}_Wheel`,
    );
  }

  for (const centerX of [-1.35, 1.35]) {
    addBeam(
      parent,
      resources.unitBox,
      new THREE.Vector3(position.x + centerX - 0.9, 0.95, position.z),
      new THREE.Vector3(position.x + centerX + 0.9, 0.95, position.z),
      0.18,
      palette.machinery,
      `${name}_Equalizer`,
    );
  }
  return group;
}

function createPortal(root, resources, palette, config) {
  const group = new THREE.Group();
  group.name = "SL_TravelAssembly";
  root.add(group);

  const engineering = config.engineering;
  const visual = config.visual;
  const halfBase = engineering.wheel_base_m * 0.5;
  const halfGauge = engineering.rail_gauge_m * 0.5;
  const halfTopLength = visual.portal_top_length_m * 0.5;
  const halfTopWidth = visual.portal_top_width_m * 0.5;
  const deckY = visual.portal_height_m - 0.55;

  const corners = [
    [-halfBase, -halfGauge, "FrontLeft"],
    [-halfBase, halfGauge, "FrontRight"],
    [halfBase, -halfGauge, "RearLeft"],
    [halfBase, halfGauge, "RearRight"],
  ];
  for (const [x, z, label] of corners) {
    createBogie(group, resources, palette, new THREE.Vector3(x, 0, z), `VIS_Bogie${label}`);
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(x, 1.25, z),
      new THREE.Vector3(
        Math.sign(x) * halfTopLength,
        deckY,
        Math.sign(z) * halfTopWidth,
      ),
      0.55,
      palette.structure,
      `VIS_PortalLeg${label}`,
    );
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(x - Math.sign(x) * 0.85, 1.25, z),
      new THREE.Vector3(
        Math.sign(x) * (halfTopLength - 0.65),
        deckY,
        Math.sign(z) * (halfTopWidth - 0.35),
      ),
      0.28,
      palette.structureDark,
      `VIS_PortalLegInner${label}`,
    );
  }

  for (const z of [-halfGauge, halfGauge]) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(-halfBase, 1.25, z),
      new THREE.Vector3(halfBase, 1.25, z),
      0.32,
      palette.structureDark,
      "VIS_RailSideEqualizerBeam",
    );
  }

  addBox(
    group,
    resources.unitBox,
    new THREE.Vector3(0, deckY, 0),
    new THREE.Vector3(visual.portal_top_length_m + 1.2, 0.7, visual.portal_top_width_m + 1.2),
    palette.structureDark,
    "VIS_PortalDeck",
  );

  for (const x of [-halfTopLength, halfTopLength]) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(x, deckY - 0.5, -halfTopWidth),
      new THREE.Vector3(x, deckY - 0.5, halfTopWidth),
      0.42,
      palette.structure,
    );
  }
  for (const z of [-halfTopWidth, halfTopWidth]) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(-halfTopLength, deckY - 0.5, z),
      new THREE.Vector3(halfTopLength, deckY - 0.5, z),
      0.42,
      palette.structure,
    );
  }

  const portalTower = new THREE.Group();
  portalTower.name = "VIS_PortalCentralTower";
  group.add(portalTower);
  const towerBottomY = deckY - 3.0;
  for (const x of [-1.7, 1.7]) {
    for (const z of [-1.45, 1.45]) {
      addBeam(
        portalTower,
        resources.unitBox,
        new THREE.Vector3(x, towerBottomY, z),
        new THREE.Vector3(x, deckY + 0.15, z),
        0.2,
        palette.structureDark,
      );
    }
  }
  for (const z of [-1.45, 1.45]) {
    addBeam(
      portalTower,
      resources.unitBox,
      new THREE.Vector3(-1.7, towerBottomY, z),
      new THREE.Vector3(1.7, deckY + 0.15, z),
      0.12,
      palette.structure,
    );
    addBeam(
      portalTower,
      resources.unitBox,
      new THREE.Vector3(1.7, towerBottomY, z),
      new THREE.Vector3(-1.7, deckY + 0.15, z),
      0.12,
      palette.structure,
    );
  }

  for (const zSign of [-1, 1]) {
    for (const xSign of [-1, 1]) {
      addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(xSign * halfBase, 1.35, zSign * halfGauge),
        new THREE.Vector3(-xSign * halfTopLength, deckY - 0.3, zSign * halfTopWidth),
        0.18,
        palette.structureDark,
      );
    }
  }

  const railingY = deckY + 0.8;
  for (const z of [-halfTopWidth - 0.45, halfTopWidth + 0.45]) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(-halfTopLength - 0.45, railingY, z),
      new THREE.Vector3(halfTopLength + 0.45, railingY, z),
      0.07,
      palette.safety,
    );
    for (let x = -halfTopLength; x <= halfTopLength + 0.01; x += 2) {
      addBeam(
        group,
        resources.unitBox,
        new THREE.Vector3(x, deckY + 0.3, z),
        new THREE.Vector3(x, railingY, z),
        0.06,
        palette.safety,
      );
    }
  }

  const ladderX = -halfTopLength - 0.2;
  const ladderZ = -halfTopWidth - 0.4;
  for (const xOffset of [-0.35, 0.35]) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(ladderX + xOffset, 1.4, ladderZ),
      new THREE.Vector3(ladderX + xOffset, deckY, ladderZ),
      0.06,
      palette.safety,
    );
  }
  for (let y = 1.8; y < deckY; y += 0.45) {
    addBeam(
      group,
      resources.unitBox,
      new THREE.Vector3(ladderX - 0.35, y, ladderZ),
      new THREE.Vector3(ladderX + 0.35, y, ladderZ),
      0.045,
      palette.safety,
    );
  }

  const feed = new THREE.Group();
  feed.name = "VIS_LandSideTransfer";
  // The fixed land-side conveyor approaches from the left in the top view.
  // Keep its inner end four metres short of the slew centre for the transfer
  // interface instead of placing it across the portal centreline.
  feed.position.set(-18, visual.portal_height_m + 0.35, 0);
  feed.rotation.y = Math.PI / 2;
  group.add(feed);
  createStaticTruss(feed, resources, {
    length: 14,
    width: 2.2,
    height: 1.45,
    panels: 7,
    material: palette.structureLight,
    name: "LandSideFeedTruss",
    beltMaterial: palette.belt,
    rollerMaterial: palette.structureDark,
  });

  return group;
}

function createUpperAssembly(root, resources, palette, config) {
  const geometry = config.geometry;
  const visual = config.visual;
  const upper = new THREE.Group();
  upper.name = "SL_UpperSlewAssembly";
  upper.position.set(0, geometry.base_height_m, 0);
  root.add(upper);

  addCylinderY(
    upper,
    resources.unitCylinder,
    new THREE.Vector3(0, 0.22, 0),
    2.15,
    0.48,
    palette.machinery,
    "VIS_SlewBearing",
  );
  addBoxInstance(
    upper,
    resources.unitBox,
    new THREE.Vector3(0, 0.68, 0),
    new THREE.Vector3(9.2, 0.55, 7.6),
    palette.structureDark,
    "VIS_SlewPlatform",
  );
  addBox(
    upper,
    resources.unitBox,
    new THREE.Vector3(-1.25, 2.05, -2.45),
    new THREE.Vector3(5.8, 2.75, 3.8),
    palette.structureLight,
    "VIS_MachineryHouse",
  );
  addBox(
    upper,
    resources.unitBox,
    new THREE.Vector3(3.55, 2.25, 0.6),
    new THREE.Vector3(2.15, 2.65, 2.4),
    palette.structure,
    "VIS_OperatorCab",
  );
  addBoxInstance(
    upper,
    resources.unitBox,
    new THREE.Vector3(3.58, 2.55, 1.82),
    new THREE.Vector3(1.7, 1.15, 0.08),
    palette.glass,
    "VIS_OperatorCabGlass",
  );
  addBoxInstance(
    upper,
    resources.unitBox,
    new THREE.Vector3(-1.25, 3.48, -2.45),
    new THREE.Vector3(6.15, 0.18, 4.1),
    palette.structureDark,
    "VIS_MachineryHouseRoof",
  );
  for (const x of [2.46, 4.64]) {
    addBoxInstance(
      upper,
      resources.unitBox,
      new THREE.Vector3(x, 2.58, 0.6),
      new THREE.Vector3(0.07, 1.15, 1.72),
      palette.glass,
      "VIS_OperatorCabSideGlass",
    );
  }
  for (const z of [-3.95, 3.95]) {
    addBeam(
      upper,
      resources.unitBox,
      new THREE.Vector3(-4.75, 1.35, z),
      new THREE.Vector3(4.75, 1.35, z),
      0.06,
      palette.safety,
      "VIS_UpperDeckRail",
    );
    for (let x = -4.7; x <= 4.71; x += 1.55) {
      addBeam(
        upper,
        resources.unitBox,
        new THREE.Vector3(x, 0.92, z),
        new THREE.Vector3(x, 1.35, z),
        0.05,
        palette.safety,
      );
    }
  }

  const counterBoom = new THREE.Group();
  counterBoom.name = "VIS_CounterBoom";
  counterBoom.position.set(0, 2.1, -0.5);
  counterBoom.rotation.y = Math.PI;
  upper.add(counterBoom);
  createStaticTruss(counterBoom, resources, {
    length: 10.5,
    width: 2.7,
    height: 2.3,
    panels: 6,
    material: palette.structure,
    name: "CounterBoomTruss",
    beltMaterial: palette.structureDark,
    rollerMaterial: palette.structureDark,
  });
  addBox(
    upper,
    resources.unitBox,
    new THREE.Vector3(0, 1.55, -11.2),
    new THREE.Vector3(5.4, 2.7, 2.2),
    palette.machinery,
    "VIS_CounterWeight",
  );

  const mastTop = new THREE.Vector3(0, 8.0, -1.2);
  for (const x of [-1.05, 1.05]) {
    addBeam(
      upper,
      resources.unitBox,
      new THREE.Vector3(x, 1.0, -1.0),
      new THREE.Vector3(x * 0.45, mastTop.y, mastTop.z),
      0.18,
      palette.structure,
      "VIS_LuffSupport",
    );
  }

  const luffPivot = new THREE.Group();
  luffPivot.name = "SL_BoomLuffPivot";
  luffPivot.position.copy(worldToThree(geometry.boom_base_offset));
  upper.add(luffPivot);

  const pivotPin = markMesh(new THREE.Mesh(resources.pivotPin, palette.machinery));
  pivotPin.name = "VIS_BoomPivotPin";
  pivotPin.rotation.z = Math.PI / 2;
  luffPivot.add(pivotPin);

  const fixedBoom = createStaticTruss(luffPivot, resources, {
    length: geometry.boom_base_length_m,
    width: visual.boom_truss_width_m,
    height: visual.boom_truss_height_m,
    panels: 9,
    material: palette.structure,
    name: "SL_FixedBoomAssembly",
    beltMaterial: palette.belt,
    rollerMaterial: palette.structureDark,
  });
  const boomMaintenance = new THREE.Group();
  boomMaintenance.name = "VIS_BoomMaintenanceWalkway";
  fixedBoom.add(boomMaintenance);
  const walkwayX = visual.boom_truss_width_m * 0.5 + 0.48;
  const walkwayY = visual.boom_truss_height_m * 0.5 + 0.08;
  addBoxInstance(
    boomMaintenance,
    resources.unitBox,
    new THREE.Vector3(walkwayX, walkwayY, geometry.boom_base_length_m * 0.5),
    new THREE.Vector3(0.72, 0.08, geometry.boom_base_length_m),
    palette.structureDark,
    "VIS_BoomWalkwayDeck",
  );
  addBeam(
    boomMaintenance,
    resources.unitBox,
    new THREE.Vector3(walkwayX + 0.36, walkwayY + 0.75, 0),
    new THREE.Vector3(
      walkwayX + 0.36,
      walkwayY + 0.75,
      geometry.boom_base_length_m,
    ),
    0.05,
    palette.safety,
    "VIS_BoomWalkwayRail",
  );
  for (let z = 0; z <= geometry.boom_base_length_m + 0.01; z += 1.8) {
    addBeam(
      boomMaintenance,
      resources.unitBox,
      new THREE.Vector3(walkwayX + 0.36, walkwayY + 0.08, z),
      new THREE.Vector3(walkwayX + 0.36, walkwayY + 0.75, z),
      0.045,
      palette.safety,
    );
  }

  const overlap = visual.telescopic_overlap_m;
  const telescopic = createAdjustableTruss(luffPivot, resources, {
    width: visual.boom_truss_width_m * 0.72,
    height: visual.boom_truss_height_m * 0.68,
    panels: 10,
    material: palette.structureLight,
    name: "SL_TelescopicBoomAssembly",
    beltMaterial: palette.belt,
    rollerMaterial: palette.structureDark,
  });
  telescopic.group.position.z = geometry.boom_base_length_m - overlap;

  const boomHead = new THREE.Group();
  boomHead.name = "SL_BoomHeadAttachment";
  luffPivot.add(boomHead);
  addBox(
    boomHead,
    resources.unitBox,
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(3.4, 0.45, 1.35),
    palette.structureDark,
    "VIS_HeadPulleyFrame",
  );
  for (const x of [-1.55, 1.55]) {
    for (const z of [-0.66, 0.66]) {
      addBeam(
        boomHead,
        resources.unitBox,
        new THREE.Vector3(x, -0.9, z),
        new THREE.Vector3(x, 0.9, z),
        0.09,
        palette.structureDark,
        "VIS_HeadPulleySupport",
      );
    }
    addBeam(
      boomHead,
      resources.unitBox,
      new THREE.Vector3(x, 0.9, -0.66),
      new THREE.Vector3(x, -0.9, 0.66),
      0.07,
      palette.structure,
    );
  }
  const headPulley = markMesh(new THREE.Mesh(resources.headPulley, palette.machinery));
  headPulley.rotation.z = Math.PI / 2;
  boomHead.add(headPulley);
  addBox(
    boomHead,
    resources.unitBox,
    new THREE.Vector3(0, -0.72, 0.55),
    new THREE.Vector3(2.2, 0.72, 1.3),
    palette.chuteSleeve,
    "VIS_TransferHopper",
  );

  const luffRopeFront = addCylinderBetween(
    upper,
    resources.unitCylinder,
    mastTop,
    new THREE.Vector3(0, 3.0, 10.0),
    0.055,
    palette.machinery,
    "VIS_LuffRopeFront",
  );
  addCylinderBetween(
    upper,
    resources.unitCylinder,
    mastTop,
    new THREE.Vector3(0, 2.4, -9.5),
    0.055,
    palette.machinery,
    "VIS_LuffRopeRear",
  );

  return {
    upper,
    luffPivot,
    fixedBoom,
    telescopic,
    boomHead,
    luffRopeFront,
    mastTop,
  };
}

function createGuardedPlatform(
  parent,
  resources,
  palette,
  {
    name,
    centerY,
    width,
    depth,
    railHeight = 0.78,
    postSpacing = 1.2,
  },
) {
  const platform = new THREE.Group();
  platform.name = name;
  platform.position.y = centerY;
  parent.add(platform);

  addBoxInstance(
    parent,
    resources.unitBox,
    new THREE.Vector3(0, centerY, 0),
    new THREE.Vector3(width, 0.18, depth),
    palette.structureDark,
    `${name}_Deck`,
  );
  const halfWidth = width * 0.5;
  const halfDepth = depth * 0.5;
  const railY = railHeight;
  for (const z of [-halfDepth, halfDepth]) {
    addBeam(
      platform,
      resources.unitBox,
      new THREE.Vector3(-halfWidth, railY, z),
      new THREE.Vector3(halfWidth, railY, z),
      0.055,
      palette.safety,
      `${name}_Rail`,
    );
    addBeam(
      platform,
      resources.unitBox,
      new THREE.Vector3(-halfWidth, railY * 0.5, z),
      new THREE.Vector3(halfWidth, railY * 0.5, z),
      0.045,
      palette.safety,
    );
    for (let x = -halfWidth; x <= halfWidth + 0.01; x += postSpacing) {
      addBeam(
        platform,
        resources.unitBox,
        new THREE.Vector3(x, 0.05, z),
        new THREE.Vector3(x, railY, z),
        0.045,
        palette.safety,
      );
    }
  }
  for (const x of [-halfWidth, halfWidth]) {
    addBeam(
      platform,
      resources.unitBox,
      new THREE.Vector3(x, railY, -halfDepth),
      new THREE.Vector3(x, railY, halfDepth),
      0.055,
      palette.safety,
    );
    for (let z = -halfDepth; z <= halfDepth + 0.01; z += postSpacing) {
      addBeam(
        platform,
        resources.unitBox,
        new THREE.Vector3(x, 0.05, z),
        new THREE.Vector3(x, railY, z),
        0.045,
        palette.safety,
      );
    }
  }
  return platform;
}

function createChute(root, resources, palette, config) {
  const geometry = config.geometry;
  const visual = config.visual;
  const chute = new THREE.Group();
  chute.name = "SL_ChuteAssembly";
  root.add(chute);

  const totalLength = geometry.chute_length_m;
  const branchLength = Math.min(visual.chute_branch_length_m, totalLength * 0.32);
  const branchSpread = Math.min(visual.chute_branch_spread_m, branchLength * 0.78);
  const branchDrop = Math.sqrt(
    Math.max(branchLength * branchLength - branchSpread * branchSpread, 0.25),
  );
  const branchPivotY = -totalLength + branchDrop;
  const lowerPlatformY = branchPivotY + 0.62;
  const trunkTopY = -3.05;
  const trunkBottomY = lowerPlatformY + 0.18;
  const trunkHeight = trunkTopY - trunkBottomY;
  const guideHalfWidth = visual.chute_guide_frame_width_m * 0.5;
  const guideHalfDepth = Math.max(visual.chute_trunk_radius_m + 0.25, 0.95);

  const suspension = new THREE.Group();
  suspension.name = "VIS_ChuteSuspensionYoke";
  chute.add(suspension);
  for (const x of [-0.62, 0.62]) {
    addBeam(
      suspension,
      resources.unitBox,
      new THREE.Vector3(x, 0.08, -1.9),
      new THREE.Vector3(x * 0.58, -1.35, -0.38),
      0.09,
      palette.machinery,
    );
    addBeam(
      suspension,
      resources.unitBox,
      new THREE.Vector3(x, 0.08, 1.9),
      new THREE.Vector3(x * 0.58, -1.35, 0.38),
      0.09,
      palette.machinery,
    );
  }
  addShapeInstance(
    suspension,
    resources.squareTransition,
    palette.chuteSleeve,
    new THREE.Vector3(0, -1.35, 0),
    new THREE.Quaternion(),
    new THREE.Vector3(0.92, 0.95, 0.8),
    "VIS_ChuteTopTransition",
  );

  createGuardedPlatform(chute, resources, palette, {
    name: "VIS_ChuteTopServicePlatform",
    centerY: -1.92,
    width: visual.chute_top_platform_width_m,
    depth: visual.chute_top_platform_depth_m,
  });
  addCylinderYInstance(
    chute,
    resources.unitCylinder,
    new THREE.Vector3(0, -2.28, 0),
    1.03,
    0.82,
    palette.chuteSleeve,
    "VIS_ChuteTopRotaryHousing",
  );
  for (const y of [-1.92, -2.68]) {
    addCylinderYInstance(
      chute,
      resources.unitCylinder,
      new THREE.Vector3(0, y, 0),
      1.18,
      0.16,
      palette.machinery,
      "VIS_ChuteRotaryCollar",
    );
  }
  for (const x of [-1.43, 1.43]) {
    addBoxInstance(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, -2.22, 0),
      new THREE.Vector3(0.58, 0.66, 0.82),
      palette.machinery,
      "VIS_ChuteTopDrive",
    );
  }
  const topCage = new THREE.Group();
  topCage.name = "VIS_ChuteTopMachineryCage";
  chute.add(topCage);
  const topCageTop = -1.05;
  const topCageBottom = -2.82;
  for (const x of [-1.52, 1.52]) {
    for (const z of [-1.28, 1.28]) {
      addBeam(
        chute,
        resources.unitBox,
        new THREE.Vector3(x, topCageTop, z),
        new THREE.Vector3(x, topCageBottom, z),
        0.07,
        palette.machinery,
      );
    }
  }
  for (const x of [-1.52, 1.52]) {
    for (const y of [topCageTop, topCageBottom]) {
      addBeam(
        chute,
        resources.unitBox,
        new THREE.Vector3(x, y, -1.28),
        new THREE.Vector3(x, y, 1.28),
        0.065,
        palette.machinery,
      );
    }
  }
  for (const x of [-1.52, 1.52]) {
    addBeam(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, topCageTop, -1.28),
      new THREE.Vector3(x, topCageBottom, 1.28),
      0.055,
      palette.structure,
    );
  }

  const trunk = new THREE.Group();
  trunk.name = "VIS_ChuteTelescopicTrunk";
  chute.add(trunk);
  const segmentHeight = trunkHeight / visual.chute_segments;
  for (let index = 0; index < visual.chute_segments; index += 1) {
    const segmentTop = trunkTopY - index * segmentHeight;
    const centerY = segmentTop - segmentHeight * 0.5;
    const radius = visual.chute_trunk_radius_m - index * 0.055;
    addCylinderYInstance(
      trunk,
      resources.unitCylinder,
      new THREE.Vector3(0, centerY, 0),
      radius,
      segmentHeight * 0.97,
      index % 2 === 0 ? palette.chuteSleeve : palette.structureLight,
      `VIS_ChuteTelescopicSection${index + 1}`,
    );
    addCylinderYInstance(
      trunk,
      resources.unitCylinder,
      new THREE.Vector3(0, segmentTop - segmentHeight, 0),
      radius + 0.16,
      0.18,
      palette.chute,
      `VIS_ChuteSectionCollar${index + 1}`,
    );
  }

  const guideFrame = new THREE.Group();
  guideFrame.name = "VIS_ChuteGuideFrame";
  chute.add(guideFrame);
  for (const x of [-guideHalfWidth, guideHalfWidth]) {
    for (const z of [-guideHalfDepth, guideHalfDepth]) {
      addBeam(
        guideFrame,
        resources.unitBox,
        new THREE.Vector3(x, trunkTopY, z),
        new THREE.Vector3(x, trunkBottomY, z),
        0.075,
        palette.structureDark,
      );
    }
  }
  const guidePanels = 5;
  for (let index = 0; index < guidePanels; index += 1) {
    const y0 = trunkTopY - (trunkHeight * index) / guidePanels;
    const y1 = trunkTopY - (trunkHeight * (index + 1)) / guidePanels;
    for (const z of [-guideHalfDepth, guideHalfDepth]) {
      addBeam(
        guideFrame,
        resources.unitBox,
        new THREE.Vector3(-guideHalfWidth, y0, z),
        new THREE.Vector3(guideHalfWidth, y1, z),
        0.045,
        palette.structure,
      );
      addBeam(
        guideFrame,
        resources.unitBox,
        new THREE.Vector3(guideHalfWidth, y0, z),
        new THREE.Vector3(-guideHalfWidth, y1, z),
        0.045,
        palette.structure,
      );
    }
  }

  const ladder = new THREE.Group();
  ladder.name = "VIS_ChuteInspectionLadder";
  chute.add(ladder);
  const ladderX = guideHalfWidth + 0.11;
  for (const z of [-0.56, 0.56]) {
    addBeam(
      ladder,
      resources.unitBox,
      new THREE.Vector3(ladderX, trunkTopY + 0.15, z),
      new THREE.Vector3(ladderX, trunkBottomY - 0.05, z),
      0.045,
      palette.safety,
    );
  }
  for (let index = 0; index < visual.chute_ladder_rungs; index += 1) {
    const fraction = index / Math.max(visual.chute_ladder_rungs - 1, 1);
    const y = trunkTopY - 0.05 - trunkHeight * fraction;
    addBeam(
      ladder,
      resources.unitBox,
      new THREE.Vector3(ladderX, y, -0.56),
      new THREE.Vector3(ladderX, y, 0.56),
      0.04,
      palette.safety,
    );
  }
  for (const x of [-guideHalfWidth - 0.38, guideHalfWidth + 0.38]) {
    addBeam(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, -2.55, 0),
      new THREE.Vector3(x, lowerPlatformY - 0.1, 0),
      0.065,
      palette.machinery,
      "VIS_ChuteHoistGuide",
    );
  }

  createGuardedPlatform(chute, resources, palette, {
    name: "VIS_ChuteLowerServicePlatform",
    centerY: lowerPlatformY,
    width: visual.chute_lower_platform_width_m,
    depth: visual.chute_lower_platform_depth_m,
    railHeight: 0.72,
  });
  addCylinderYInstance(
    chute,
    resources.unitCylinder,
    new THREE.Vector3(0, branchPivotY + 0.2, 0),
    1.2,
    0.95,
    palette.chuteSleeve,
    "VIS_ChuteLowerRotaryHead",
  );
  for (const x of [-1.62, 1.62]) {
    addBoxInstance(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, branchPivotY + 0.32, 0),
      new THREE.Vector3(0.62, 0.62, 0.9),
      palette.machinery,
      "VIS_ChuteLowerDrive",
    );
  }
  const lowerCage = new THREE.Group();
  lowerCage.name = "VIS_ChuteLowerMachineryCage";
  chute.add(lowerCage);
  const lowerCageTop = lowerPlatformY + 0.72;
  const lowerCageBottom = branchPivotY - 0.08;
  for (const x of [-1.72, 1.72]) {
    for (const z of [-1.35, 1.35]) {
      addBeam(
        chute,
        resources.unitBox,
        new THREE.Vector3(x, lowerCageTop, z),
        new THREE.Vector3(x, lowerCageBottom, z),
        0.065,
        palette.machinery,
      );
    }
  }
  for (const x of [-1.72, 1.72]) {
    addBeam(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, lowerCageTop, -1.35),
      new THREE.Vector3(x, lowerCageBottom, 1.35),
      0.05,
      palette.structure,
    );
    addBeam(
      chute,
      resources.unitBox,
      new THREE.Vector3(x, lowerCageTop, 1.35),
      new THREE.Vector3(x, lowerCageBottom, -1.35),
      0.05,
      palette.structure,
    );
  }

  const yaw = new THREE.Group();
  yaw.name = "SL_ChuteYawAssembly";
  yaw.position.set(0, branchPivotY, 0);
  chute.add(yaw);
  addBoxInstance(
    yaw,
    resources.unitBox,
    new THREE.Vector3(0, -0.12, 0),
    new THREE.Vector3(3.25, 0.46, 1.65),
    palette.machinery,
    "VIS_ChuteDistributionYoke",
  );

  // The SL15 detail drawing has one discharge outlet. In the front view the
  // retained negative-Z branch is the outlet on the right-hand side.
  const dischargeSign = -1;
  const branch = new THREE.Group();
  branch.name = "VIS_ChuteSingleDischarge";
  yaw.add(branch);
  const start = new THREE.Vector3(0, -0.22, dischargeSign * 0.34);
  const end = new THREE.Vector3(0, -branchDrop, dischargeSign * branchSpread);
  addTaperedDuctBetween(
    branch,
    resources.taperedDuct,
    start,
    end,
    0.68,
    0.54,
    palette.chute,
    `${branch.name}_Duct`,
  );
  for (const x of [-0.58, 0.58]) {
    addBeam(
      branch,
      resources.unitBox,
      new THREE.Vector3(x, start.y + 0.22, start.z - dischargeSign * 0.22),
      new THREE.Vector3(x, end.y + 0.18, end.z - dischargeSign * 0.32),
      0.055,
      palette.machinery,
    );
    addBeam(
      branch,
      resources.unitBox,
      new THREE.Vector3(x, start.y - 0.22, start.z + dischargeSign * 0.22),
      new THREE.Vector3(x, end.y - 0.18, end.z + dischargeSign * 0.32),
      0.055,
      palette.machinery,
    );
    addBeam(
      branch,
      resources.unitBox,
      new THREE.Vector3(x, start.y + 0.22, start.z - dischargeSign * 0.22),
      new THREE.Vector3(x, end.y - 0.18, end.z + dischargeSign * 0.32),
      0.045,
      palette.structure,
    );
  }
  addBoxInstance(
    branch,
    resources.unitBox,
    end,
    new THREE.Vector3(1.05, 0.28, 1.25),
    palette.structureDark,
    `${branch.name}_Outlet`,
  );

  addBeam(
    yaw,
    resources.unitBox,
    new THREE.Vector3(2.05, -0.35, 0.72),
    new THREE.Vector3(2.05, -branchDrop - 0.45, 0.72),
    0.035,
    palette.machinery,
    "VIS_ChuteHangingCable",
  );

  return { chute, yaw };
}

function countTriangles(object) {
  let triangles = 0;
  let meshes = 0;
  const geometries = new Set();
  object.traverse((child) => {
    if (!child.isMesh) {
      return;
    }
    meshes += 1;
    geometries.add(child.geometry);
    const multiplier = child.isInstancedMesh ? child.count : 1;
    const count = child.geometry.index
      ? child.geometry.index.count
      : child.geometry.attributes.position?.count ?? 0;
    triangles += Math.floor(count / 3) * multiplier;
  });
  return { triangles, meshes, geometries: geometries.size };
}

export class ProceduralShiploaderRig {
  constructor(config) {
    this.config = config;
    this.palette = createPalette();
    this.resources = {
      unitBox: new THREE.BoxGeometry(1, 1, 1),
      unitCylinder: new THREE.CylinderGeometry(1, 1, 1, 18),
      wheel: new THREE.CylinderGeometry(0.56, 0.56, 0.44, 18),
      roller: new THREE.CylinderGeometry(0.11, 0.11, 1.7, 12),
      pivotPin: new THREE.CylinderGeometry(0.52, 0.52, 3.8, 20),
      headPulley: new THREE.CylinderGeometry(0.72, 0.72, 3.0, 24),
      squareTransition: new THREE.CylinderGeometry(0.62, 1.0, 1, 4, 1, false),
      taperedDuct: new THREE.CylinderGeometry(0.68, 1.0, 1, 4, 1, false),
    };

    this.root = new THREE.Group();
    this.root.name = "SL_ShipLoaderRoot";
    this.travelAssembly = createPortal(this.root, this.resources, this.palette, config);
    const upper = createUpperAssembly(this.root, this.resources, this.palette, config);
    this.upperSlewAssembly = upper.upper;
    this.boomLuffPivot = upper.luffPivot;
    this.telescopicBoom = upper.telescopic;
    this.boomHead = upper.boomHead;
    this.luffRopeFront = upper.luffRopeFront;
    this.mastTop = upper.mastTop;
    const chute = createChute(this.root, this.resources, this.palette, config);
    this.chuteAssembly = chute.chute;
    this.chuteYawAssembly = chute.yaw;

    const geometry = config.geometry;
    const dischargeOffset = worldToThree(geometry.discharge_offset);
    this.markers = {
      slew_center_position: addMarker(
        this.root,
        "MK_SLEW_CENTER",
        new THREE.Vector3(0, geometry.base_height_m, 0),
      ),
      boom_root_position: addMarker(this.boomLuffPivot, "MK_BOOM_ROOT"),
      fixed_boom_tip_position: addMarker(
        this.boomLuffPivot,
        "MK_FIXED_BOOM_TIP",
        new THREE.Vector3(0, 0, geometry.boom_base_length_m),
      ),
      boom_tip_position: addMarker(this.boomHead, "MK_BOOM_TIP"),
      chute_top_position: addMarker(this.chuteAssembly, "MK_CHUTE_TOP"),
      chute_bottom_position: addMarker(
        this.chuteAssembly,
        "MK_CHUTE_BOTTOM",
        new THREE.Vector3(0, -geometry.chute_length_m, 0),
      ),
      discharge_point: addMarker(
        this.chuteAssembly,
        "MK_DISCHARGE",
        new THREE.Vector3(
          dischargeOffset.x,
          -geometry.chute_length_m + dischargeOffset.y,
          dischargeOffset.z,
        ),
      ),
    };

    this.updateCount = 0;
    this.geometryBuildCount = 1;
    this.maxKeypointErrorM = 0;
    this.lastKeypointErrors = {};
    this.ropeEndpoint = new THREE.Vector3();
    this.modelStats = countTriangles(this.root);
  }

  update(snapshot) {
    const geometry = this.config.geometry;
    const axes = snapshot.axis_states;
    const base = worldToThree(snapshot.key_points.base_position);
    this.root.position.set(base.x, base.y - geometry.base_height_m, base.z);

    this.upperSlewAssembly.rotation.y = worldYawToThreeRadians(axes.slew.current);
    this.boomLuffPivot.rotation.x = worldLuffToThreeRadians(axes.boom_luff.current);
    this.ropeEndpoint.set(0, 0.85, 10.0)
      .applyAxisAngle(RIGHT, this.boomLuffPivot.rotation.x)
      .add(this.boomLuffPivot.position);
    setCylinderTransform(this.luffRopeFront, this.mastTop, this.ropeEndpoint, 0.055);

    const extension = axes.boom_extension.current;
    const overlap = this.config.visual.telescopic_overlap_m;
    this.telescopicBoom.setLength(Math.max(overlap, overlap + extension));
    this.boomHead.position.set(0, 0, geometry.boom_base_length_m + extension);

    const chuteTop = worldToThree(snapshot.key_points.chute_top_position);
    this.chuteAssembly.position.copy(chuteTop).sub(this.root.position);
    this.chuteAssembly.rotation.y = worldYawToThreeRadians(axes.slew.current);
    this.chuteYawAssembly.rotation.y = worldYawToThreeRadians(axes.chute_rotate.current);

    this.root.updateMatrixWorld(true);
    this.audit(snapshot);
    this.updateCount += 1;
  }

  audit(snapshot) {
    const expected = new THREE.Vector3();
    const actual = new THREE.Vector3();
    let maximum = 0;
    const errors = {};
    for (const [field, marker] of Object.entries(this.markers)) {
      worldToThree(snapshot.key_points[field], expected);
      marker.getWorldPosition(actual);
      const error = actual.distanceTo(expected);
      errors[field] = error;
      maximum = Math.max(maximum, error);
    }
    this.lastKeypointErrors = errors;
    this.maxKeypointErrorM = maximum;
    return maximum;
  }

  getDiagnostics() {
    return {
      variantId: this.config.variant_id,
      assetRevision: this.config.visual.asset_revision,
      modelMode: this.config.visual.model_mode,
      geometryBuildCount: this.geometryBuildCount,
      updateCount: this.updateCount,
      maxKeypointErrorM: this.maxKeypointErrorM,
      keypointErrors: { ...this.lastKeypointErrors },
      ...this.modelStats,
    };
  }

  setMaintenanceVisible(visible) {
    const maintenance = this.root.getObjectByName("VIS_Maintenance");
    if (maintenance) {
      maintenance.visible = visible;
    }
  }

  dispose() {
    for (const geometry of Object.values(this.resources)) {
      geometry.dispose();
    }
    for (const material of Object.values(this.palette)) {
      material.dispose();
    }
  }
}
