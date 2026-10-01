"""Yard machine geometry calibration: versioned forward kinematics for the boom
discharge point and the bucket-wheel cutting envelope.

The calibration reproduces the 12-pose Unity preview-scene probe (GeometryProbe.cs):
boom hinge at model height 8.5, wheel centre at boom-local (34, 0.5), discharge
marker at boom-local (33, 0.3), model scale 0.455. The wheel envelope radius and
axial extent are measured from actual mesh vertices and are never enlarged for
reachability. Unity-side markers are comparison aids only; this module is the
backend truth source for derived geometry. Travel candidates are recorded here
as versioned proposals and deliberately leave the official machine config alone.
"""
import json
import math
from pathlib import Path

from .errors import finite

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/geometry.json"

POSE_AXES = ("travel", "slew", "luff")


def _finite_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


class GeometryCalibration:
    def __init__(self, config=None):
        self.config = config or json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        self._validate_config()
        kinematics = self.config["kinematics"]
        self.scale = kinematics["scale"]
        self.pivot_height = kinematics["pivot_height"]
        self.wheel_u, self.wheel_v = kinematics["wheel_center_boom_local"]
        self.outlet_u, self.outlet_v = kinematics["outlet_boom_local"]
        wheel = self.config["wheel"]
        self.swept_radius = wheel["swept_radius"]
        self.axial_min = wheel["axial_min"]
        self.axial_max = wheel["axial_max"]

    def _validate_config(self):
        c = self.config
        for key in ("version", "source", "kinematics", "wheel", "travel_candidates", "probe_evidence"):
            if key not in c:
                raise ValueError("Missing geometry config section: %s" % key)
        kinematics = c["kinematics"]
        for key in ("scale", "pivot_height"):
            if not _finite_number(kinematics.get(key)) or kinematics[key] <= 0:
                raise ValueError("Invalid geometry kinematics parameter: %s" % key)
        for key in ("wheel_center_boom_local", "outlet_boom_local"):
            point = kinematics.get(key)
            if (not isinstance(point, list) or len(point) != 2
                    or any(not _finite_number(v) for v in point)):
                raise ValueError("Invalid boom-local point: %s" % key)
            if point[0] <= 0:
                raise ValueError("Boom-local points must lie forward of the hinge: %s" % key)
        wheel = c["wheel"]
        for key in ("swept_radius", "axial_min", "axial_max"):
            if not _finite_number(wheel.get(key)):
                raise ValueError("Invalid wheel geometry parameter: %s" % key)
        if wheel["swept_radius"] <= 0 or wheel["axial_min"] >= wheel["axial_max"]:
            raise ValueError("Wheel envelope radius or axial extent invalid")
        candidates = c["travel_candidates"]
        if not candidates.get("version") or not isinstance(candidates.get("machines"), dict):
            raise ValueError("Travel candidates must carry a version and machine map")
        if not isinstance(candidates.get("applied"), bool):
            raise ValueError("Travel candidates must record whether they are applied")

    def validate_against_machines(self, machines):
        """Fail fast when the calibration cannot apply to the machine fleet."""
        for machine in machines:
            scene = machine.get("scene") or {}
            for key in ("x", "y", "z", "yaw", "scale"):
                if key not in scene:
                    raise ValueError("Machine %s scene config missing %s" % (machine.get("machine_id"), key))
            if scene["scale"] != self.scale:
                raise ValueError("Machine %s scene scale %s does not match calibration scale %s"
                                 % (machine["machine_id"], scene["scale"], self.scale))
            for axis in POSE_AXES:
                if axis not in machine.get("axes", {}):
                    raise ValueError("Machine %s lacks %s axis" % (machine.get("machine_id"), axis))
        for machine_id in self.config["travel_candidates"]["machines"]:
            if machine_id not in {m["machine_id"] for m in machines}:
                raise ValueError("Travel candidate references unknown machine %s" % machine_id)

    def _boom_point(self, scene, travel, slew, luff, u, v):
        theta = math.radians(scene["yaw"] - slew)
        boom_x, boom_z = math.cos(theta), -math.sin(theta)
        angle = math.radians(luff)
        along = u * math.cos(angle) - v * math.sin(angle)
        above = u * math.sin(angle) + v * math.cos(angle)
        return dict(
            x=travel + boom_x * self.scale * along,
            y=scene["y"] + self.scale * (self.pivot_height + above),
            z=scene["z"] + boom_z * self.scale * along,
        )

    def discharge_point(self, scene, travel, slew, luff):
        """Boom-front discharge marker in world metres; never the wheel centre."""
        travel, slew, luff = finite(travel), finite(slew), finite(luff)
        return self._boom_point(scene, travel, slew, luff, self.outlet_u, self.outlet_v)

    def wheel_envelope(self, scene, travel, slew, luff):
        """Full-revolution bucket-wheel cutting envelope from the measured geometry."""
        travel, slew, luff = finite(travel), finite(slew), finite(luff)
        theta = math.radians(scene["yaw"] - slew)
        return dict(
            center=self._boom_point(scene, travel, slew, luff, self.wheel_u, self.wheel_v),
            swept_radius=self.swept_radius,
            axle=dict(x=math.sin(theta), z=math.cos(theta)),
            axial_min=self.axial_min,
            axial_max=self.axial_max,
        )


def contact_volume(envelope, grid):
    """Intersection volume of a full-revolution wheel envelope with a heightfield.

    Upper-bound contact check, the production counterpart of the prototype
    contact_probe.py computation: the wheel disc is the vertical circle of the
    measured envelope at each axial position, coal occupies [ground, ground +
    height] per cell. It does not model per-step bucket filling, achievable
    rate, or slope relaxation.
    """
    center = envelope["center"]
    cx, cy, cz = center["x"], center["y"], center["z"]
    radius = envelope["swept_radius"]
    axle_x, axle_z = envelope["axle"]["x"], envelope["axle"]["z"]
    axial_min, axial_max = envelope["axial_min"], envelope["axial_max"]
    ground = grid["ground"]
    cell = grid["cell"]
    cell_area = cell * cell
    heights = grid["heights"]
    total = 0.0
    for j in range(grid["cells_z"]):
        pz = grid["origin_z"] + (j + 0.5) * cell
        dz = pz - cz
        for i in range(grid["cells_x"]):
            height = heights[j * grid["cells_x"] + i]
            if height <= 0:
                continue
            px = grid["origin_x"] + (i + 0.5) * cell
            dx = px - cx
            axial = dx * axle_x + dz * axle_z
            if axial < axial_min or axial > axial_max:
                continue
            radial = -dx * axle_z + dz * axle_x
            root_squared = radius * radius - radial * radial
            if root_squared <= 0:
                continue
            root = math.sqrt(root_squared)
            low = max(ground, cy - root)
            high = cy + root
            overlap = min(ground + height, high) - low
            if overlap > 0:
                total += overlap * cell_area
    return total
