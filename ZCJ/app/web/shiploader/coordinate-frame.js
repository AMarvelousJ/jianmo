import * as THREE from "three";

export function worldToThree(value, target = new THREE.Vector3()) {
  const [x, y, z] = value;
  return target.set(x, z, y);
}

export function threeToWorld(value) {
  return [value.x, value.z, value.y];
}

export function worldYawToThreeRadians(degrees) {
  return -THREE.MathUtils.degToRad(degrees);
}

export function worldLuffToThreeRadians(degrees) {
  return -THREE.MathUtils.degToRad(degrees);
}
