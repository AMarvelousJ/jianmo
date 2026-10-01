import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yard_motion.api import create_app
from yard_motion.errors import MotionError
from yard_motion.geometry import GeometryCalibration, contact_volume
from yard_motion.world import World

ROOT = Path(__file__).resolve().parents[1]
MACHINES = json.loads((ROOT / "config/machines.json").read_text(encoding="utf-8"))
POSES = json.loads((Path(__file__).resolve().parent / "fixtures/unity_geometry_poses.json").read_text(encoding="utf-8"))
GEOMETRY_CONFIG = json.loads((ROOT / "config/geometry.json").read_text(encoding="utf-8"))


def scene_of(machine_id):
    for machine in MACHINES["machines"]:
        if machine["machine_id"] == machine_id:
            return machine["scene"]
    raise KeyError(machine_id)


def test_fk_reproduces_all_twelve_probe_poses_within_recorded_tolerance():
    geometry = GeometryCalibration()
    tolerance = 1e-4  # observed max error ~1e-8 m; the probe's own sanity threshold was 0.02 m
    worst = 0.0
    assert len(POSES) == 12
    for record in POSES:
        scene = scene_of(record["machine_id"])
        envelope = geometry.wheel_envelope(scene, record["travel"], record["slew"], record["luff"])
        for axis, measured in zip(("x", "y", "z"), record["wheel_center"]):
            error = abs(envelope["center"][axis] - measured)
            worst = max(worst, error)
            assert error <= tolerance, (record["machine_id"], record["luff"], axis, error)
        assert abs(envelope["swept_radius"] - record["wheel_swept_radius"]) <= 5e-6
        assert abs(envelope["axial_min"] - record["wheel_axial_min"]) <= 5e-6
        assert abs(envelope["axial_max"] - record["wheel_axial_max"]) <= 5e-6
        outlet = geometry.discharge_point(scene, record["travel"], record["slew"], record["luff"])
        for axis, measured in zip(("x", "y", "z"), record["candidate_outlet"]):
            error = abs(outlet[axis] - measured)
            worst = max(worst, error)
            assert error <= tolerance, (record["machine_id"], record["luff"], axis, error)
    # recorded pose-check error of the calibration against the Unity model
    assert worst <= tolerance


def test_outlet_marker_is_distinct_from_wheel_center():
    geometry = GeometryCalibration()
    scene = scene_of("ST01")
    envelope = geometry.wheel_envelope(scene, -410.0, 90.0, 0.0)
    outlet = geometry.discharge_point(scene, -410.0, 90.0, 0.0)
    distance = math.dist((outlet["x"], outlet["y"], outlet["z"]),
                         (envelope["center"]["x"], envelope["center"]["y"], envelope["center"]["z"]))
    # boom-local (33, 0.3) vs wheel (34, 0.5): the discharge point is never the wheel centre
    assert distance == pytest.approx(0.455 * math.hypot(1.0, 0.2), abs=1e-9)
    assert distance > 0.1


def test_axle_is_horizontal_and_perpendicular_to_probe_measured_boom():
    # the wheel spins about boom-local z (YardMachineRigController wheels around Vector3.forward),
    # so the axle must be a horizontal unit vector perpendicular to the boom azimuth. The boom
    # azimuth is measurable from the probe: the wheel centre's horizontal offset from the machine
    # origin (travel x, track z) lies along the boom.
    geometry = GeometryCalibration()
    for record in POSES:
        scene = scene_of(record["machine_id"])
        envelope = geometry.wheel_envelope(scene, record["travel"], record["slew"], record["luff"])
        axle_x, axle_z = envelope["axle"]["x"], envelope["axle"]["z"]
        assert math.hypot(axle_x, axle_z) == pytest.approx(1.0, abs=1e-9)
        boom_x = record["wheel_center"][0] - record["travel"]
        boom_z = record["wheel_center"][2] - scene["z"]
        # tolerance covers the float32 export precision of the measured wheel centre
        assert axle_x * boom_x + axle_z * boom_z == pytest.approx(0.0, abs=1e-4)
    # contact_probe.py records that at yaw 180 / slew 90 the wheel local z maps to world +x
    rc = next(p for p in POSES if p["machine_id"] == "RC01" and p["luff"] == -8)
    envelope = geometry.wheel_envelope(scene_of("RC01"), rc["travel"], rc["slew"], rc["luff"])
    assert envelope["axle"]["x"] == pytest.approx(1.0, abs=1e-9)
    assert envelope["axle"]["z"] == pytest.approx(0.0, abs=1e-9)


def test_travel_candidates_are_versioned_but_not_applied_to_official_config():
    candidates = GEOMETRY_CONFIG["travel_candidates"]
    assert candidates["version"]
    assert candidates["source"]
    assert candidates["applied"] is False
    assert candidates["machines"]["ST01"]["maximum"] == -395.0
    assert candidates["machines"]["RC01"]["minimum"] == -425.0
    # the official machine config keeps its shipped travel ranges untouched
    st01 = next(m for m in MACHINES["machines"] if m["machine_id"] == "ST01")
    rc01 = next(m for m in MACHINES["machines"] if m["machine_id"] == "RC01")
    assert st01["axes"]["travel"]["maximum"] == -425.0
    assert rc01["axes"]["travel"]["minimum"] == -405.0


def test_motion_backend_does_not_enforce_travel_candidates():
    world = World()
    lease = world.acquire("ST01", "candidate-test")
    with pytest.raises(MotionError) as info:
        world.command("ST01", lease["client_id"], lease["token"], lease["generation"],
                      "beyond-candidate", 1, "set_targets", {"targets": {"travel": -400.0}})
    assert info.value.code == "OUT_OF_RANGE"


def pose_machine(world, machine_id, targets, command_id):
    lease = world.acquire(machine_id, "geometry-test")
    credentials = (lease["client_id"], lease["token"], lease["generation"])
    world.command(machine_id, *credentials, command_id, 1, "set_targets", {"targets": targets})
    try:
        for _ in range(600):
            world.advance(1)
            snapshot = world.state()["machines"][machine_id]
            if all(snapshot["axes"][axis]["mode"] == "idle" for axis in targets):
                break
        else:
            raise AssertionError("machine never settled at target pose")
    finally:
        world.release(machine_id, *credentials)
    snapshot = world.state()["machines"][machine_id]
    for axis, value in targets.items():
        assert snapshot["axes"][axis]["position"] == pytest.approx(value, abs=1e-6)
    return snapshot


def test_world_derives_geometry_from_authoritative_pose():
    world = World()
    pose_machine(world, "ST01", {"travel": -500.0, "slew": 90.0, "luff": 0.0}, "pose-1")
    geometry = world.machine_geometry("ST01")
    assert geometry["machine_id"] == "ST01"
    assert geometry["geometry_version"] == GEOMETRY_CONFIG["version"]
    assert geometry["pose"] == pytest.approx({"travel": -500.0, "slew": 90.0, "luff": 0.0})
    outlet = geometry["discharge_point"]
    # ST01 boom at slew 90 points +z from track z=-228; marker reach 0.455*33, height 0.455*(8.5+0.3)
    assert outlet["x"] == pytest.approx(-500.0, abs=1e-9)
    assert outlet["z"] == pytest.approx(-228.0 + 0.455 * 33.0, abs=1e-9)
    assert outlet["y"] == pytest.approx(0.455 * (8.5 + 0.3), abs=1e-9)
    envelope = geometry["wheel_envelope"]
    assert envelope["center"]["x"] == pytest.approx(-500.0, abs=1e-9)
    assert envelope["center"]["z"] == pytest.approx(-228.0 + 0.455 * 34.0, abs=1e-9)
    assert envelope["center"]["y"] == pytest.approx(0.455 * (8.5 + 0.5), abs=1e-9)
    # derived geometry follows the machine when the authoritative pose moves
    pose_machine(world, "ST01", {"travel": -505.0}, "pose-2")
    assert world.machine_geometry("ST01")["discharge_point"]["x"] == pytest.approx(-505.0, abs=1e-9)


def test_api_exposes_geometry_config_and_machine_geometry():
    world = World()
    client = TestClient(create_app(world, run_clock=False))
    config = client.get("/api/geometry/config").json()
    assert config["version"] == "yard-geometry-probe-v1"
    assert config["demo"] is True
    assert config["source"]
    assert config["travel_candidates"]["machines"]["ST01"]["maximum"] == -395.0
    assert config["probe_evidence"]["full_revolution_contact_m3"] == pytest.approx(0.760621, abs=1e-6)
    assert "token" not in json.dumps(config)
    assert "lease" not in json.dumps(config)
    pose_machine(world, "RC01", {"travel": -400.0, "slew": 90.0, "luff": -8.0}, "api-pose")
    response = client.get("/api/machines/RC01/geometry")
    assert response.status_code == 200
    body = response.json()
    assert body["machine_id"] == "RC01"
    assert body["discharge_point"]["x"] == pytest.approx(-400.0, abs=1e-9)
    envelope = body["wheel_envelope"]
    # RC01 (yaw 180) boom points -z at slew 90; wheel axle maps to +x, matching the probe convention
    # hand-derived reach at luff -8: 0.455*(34*cos(-8deg) - 0.5*sin(-8deg)) (probe measured z -207.3511)
    reach = 0.455 * (34.0 * math.cos(math.radians(-8.0)) - 0.5 * math.sin(math.radians(-8.0)))
    assert envelope["center"]["z"] == pytest.approx(-192.0 - reach, abs=1e-9)
    assert envelope["axle"]["x"] == pytest.approx(1.0, abs=1e-9)
    assert envelope["axle"]["z"] == pytest.approx(0.0, abs=1e-9)
    assert client.get("/api/machines/NOPE/geometry").status_code == 404


def load_contact_fixture():
    fixture = json.loads((Path(__file__).resolve().parent / "fixtures/contact_pile.json").read_text(encoding="utf-8"))
    grid = dict(fixture["grid"])
    grid["heights"] = [0.0] * (grid["cells_x"] * grid["cells_z"])
    for key, value in fixture["heights"].items():
        j, i = (int(part) for part in key.split(","))
        grid["heights"][j * grid["cells_x"] + i] = value
    return fixture, grid


def test_contact_volume_reproduces_probe_envelope_result():
    fixture, grid = load_contact_fixture()
    probe = fixture["envelope_probe"]
    envelope = dict(center=dict(zip(("x", "y", "z"), probe["center"])),
                    swept_radius=probe["swept_radius"],
                    axle=dict(zip(("x", "z"), probe["axle"])),
                    axial_min=probe["axial_min"],
                    axial_max=probe["axial_max"])
    contact = contact_volume(envelope, grid)
    assert contact == pytest.approx(fixture["expected"]["full_revolution_contact_m3"], abs=1e-6)


def test_contact_volume_with_fk_envelope_matches_probe_conclusion():
    fixture, grid = load_contact_fixture()
    geometry = GeometryCalibration()
    envelope = geometry.wheel_envelope(scene_of("RC01"), -410.0, 90.0, -8.0)
    origin_x, origin_z = fixture["frame"]["origin_world"]
    # translate the world-frame envelope into the prototype local frame of the fixture
    envelope["center"]["x"] -= origin_x
    envelope["center"]["z"] -= origin_z
    contact = contact_volume(envelope, grid)
    # residual vs the probe value is dominated by the float32 export precision of the
    # measured wheel centre (~1e-5 m), not by the calibration kinematics
    assert contact == pytest.approx(fixture["expected"]["full_revolution_contact_m3"], abs=1e-4)
