import pytest
from fastapi.testclient import TestClient

from yard_motion.api import create_app
from yard_motion.errors import MotionError
from yard_motion.world import World

START_PAYLOAD = {"zone": "north-12", "mode": "manual", "requested_flow_t_per_h": 3000.0}


class Operator:
    def __init__(self, world, machine_id, client_id="stack-test"):
        self.world = world
        self.machine_id = machine_id
        lease = world.acquire(machine_id, client_id)
        self.creds = (lease["client_id"], lease["token"], lease["generation"])
        self.seq = 0

    def send(self, kind, payload=None, command_id=None):
        self.seq += 1
        return self.world.command(self.machine_id, *self.creds,
                                  command_id or "%s-%d" % (kind, self.seq), self.seq, kind, payload or {})

    def settle(self, targets, limit=200):
        self.send("set_targets", {"targets": targets})
        for _ in range(limit):
            self.world.advance(1)
            snapshot = self.world.state()["machines"][self.machine_id]
            if all(snapshot["axes"][axis]["mode"] == "idle" for axis in targets):
                return
        raise AssertionError("machine never settled at target pose")


def ready_world():
    # frozen wall clock: long stacking scenarios must not lose leases to real time
    world = World(clock=lambda: 0.0)
    world.init_material("empty")
    return world


def only_job(world):
    jobs = world.state()["jobs"]
    assert len(jobs) == 1
    return next(iter(jobs.values()))


def test_start_job_creates_manual_stacking_job():
    world = ready_world()
    op = Operator(world, "ST01")
    result = op.send("start_job", START_PAYLOAD)
    assert result["accepted"] is True
    record = only_job(world)
    assert record["machine_id"] == "ST01"
    assert record["zone"] == "north-12"
    assert record["mode"] == "manual"
    assert record["role"] == "stacking"
    assert record["requested_flow_t_per_h"] == 3000.0
    assert record["status"] == "running"
    assert record["completed_t"] == 0.0
    assert record["actual_flow_t_per_h"] == 0.0
    assert record["reason"] is None
    assert record["plan_version"] == "manual"
    assert record["target_t"] is None
    assert record["job_id"]


def test_start_job_requires_control_and_replays_idempotently():
    world = ready_world()
    with pytest.raises(MotionError) as info:
        world.command("ST01", "intruder", "no-token", 1, "steal", 1, "start_job", START_PAYLOAD)
    assert info.value.code == "CONTROL_REQUIRED"
    op = Operator(world, "ST01")
    first = op.send("start_job", START_PAYLOAD)
    replay = world.command("ST01", *op.creds, first["command_id"], op.seq, "start_job", START_PAYLOAD)
    assert replay == first
    assert len(world.state()["jobs"]) == 1
    with pytest.raises(MotionError) as info:
        world.command("ST01", *op.creds, first["command_id"], op.seq, "start_job",
                      dict(START_PAYLOAD, requested_flow_t_per_h=20.0))
    assert info.value.code == "INVALID_COMMAND"
    assert len(world.state()["jobs"]) == 1


def test_start_job_validates_zone_mode_and_flow():
    world = ready_world()
    op = Operator(world, "ST01")
    invalid = [
        {"zone": "nowhere", "mode": "manual", "requested_flow_t_per_h": 10.0},
        {"zone": "north-12", "mode": "automatic", "requested_flow_t_per_h": 10.0},
        {"zone": "north-12", "mode": "manual", "requested_flow_t_per_h": 0.0},
        {"zone": "north-12", "mode": "manual", "requested_flow_t_per_h": -5.0},
        {"zone": "north-12", "mode": "manual", "requested_flow_t_per_h": float("nan")},
        {"zone": "north-12", "mode": "manual"},
    ]
    for payload in invalid:
        with pytest.raises(MotionError) as info:
            op.send("start_job", payload)
        assert info.value.code == "INVALID_COMMAND", payload
    assert world.state()["jobs"] == {}


def test_start_job_outside_pilot_pair_is_unsupported():
    world = ready_world()
    op = Operator(world, "RC02")
    with pytest.raises(MotionError) as info:
        op.send("start_job", START_PAYLOAD)
    assert info.value.code == "JOB_UNSUPPORTED"


def test_start_job_requires_initialized_material_scene():
    world = World()
    op = Operator(world, "ST01")
    with pytest.raises(MotionError) as info:
        op.send("start_job", START_PAYLOAD)
    assert info.value.code == "MATERIAL_UNINITIALIZED"


def test_second_start_job_on_same_machine_is_rejected():
    world = ready_world()
    op = Operator(world, "ST01")
    op.send("start_job", START_PAYLOAD)
    with pytest.raises(MotionError) as info:
        op.send("start_job", START_PAYLOAD)
    assert info.value.code == "JOB_ACTIVE"
    op.send("terminate_job")
    op.send("start_job", START_PAYLOAD)
    assert len(world.state()["jobs"]) == 2


def test_job_lifecycle_pause_resume_terminate():
    world = ready_world()
    op = Operator(world, "ST01")
    op.send("start_job", START_PAYLOAD)
    job_id = only_job(world)["job_id"]

    op.send("pause_job")
    paused = world.state()["jobs"][job_id]
    assert paused["status"] == "paused"
    assert paused["actual_flow_t_per_h"] == 0.0
    with pytest.raises(MotionError) as info:
        op.send("pause_job")
    assert info.value.code == "JOB_STATE"

    op.send("resume_job")
    assert world.state()["jobs"][job_id]["status"] == "running"
    with pytest.raises(MotionError) as info:
        op.send("resume_job")
    assert info.value.code == "JOB_STATE"

    op.send("terminate_job")
    terminated = world.state()["jobs"][job_id]
    assert terminated["status"] == "terminated"
    assert terminated["actual_flow_t_per_h"] == 0.0
    with pytest.raises(MotionError) as info:
        op.send("pause_job")
    assert info.value.code == "JOB_NONE"


def test_material_reinit_is_refused_while_job_active():
    world = ready_world()
    op = Operator(world, "ST01")
    op.send("start_job", START_PAYLOAD)
    with pytest.raises(MotionError) as info:
        world.init_material("empty", confirm=True)
    assert info.value.code == "JOB_ACTIVE"
    op.send("pause_job")
    with pytest.raises(MotionError) as info:
        world.init_material("empty", confirm=True)
    assert info.value.code == "JOB_ACTIVE"
    op.send("terminate_job")
    assert world.init_material("empty", confirm=True)["scene"] == "empty"


def test_estop_blocks_start_pauses_job_and_allows_terminate():
    world = ready_world()
    op = Operator(world, "ST01")
    op.send("start_job", START_PAYLOAD)
    op.send("estop")
    assert only_job(world)["status"] == "paused"
    op.send("terminate_job")
    with pytest.raises(MotionError) as info:
        op.send("start_job", START_PAYLOAD)
    assert info.value.code == "ESTOP_LATCHED"
    op.send("clear_estop")
    op.send("start_job", START_PAYLOAD)
    jobs = world.state()["jobs"]
    assert len(jobs) == 2
    running = [job for job in jobs.values() if job["status"] == "running"]
    assert len(running) == 1 and running[0]["machine_id"] == "ST01"


def test_api_routes_material_job_commands_and_state():
    world = ready_world()
    client = TestClient(create_app(world, run_clock=False))
    lease = client.post("/api/machines/ST01/control/acquire", json={"client_id": "unity"}).json()
    body = dict(client_id="unity", token=lease["token"], generation=lease["generation"],
                command_id="start-1", command_seq=1, kind="start_job", payload=START_PAYLOAD)
    assert client.post("/api/machines/ST01/commands", json=body).status_code == 200
    jobs = client.get("/api/state").json()["jobs"]
    assert len(jobs) == 1
    record = next(iter(jobs.values()))
    assert record["machine_id"] == "ST01"
    assert record["requested_flow_t_per_h"] == 3000.0
    intruder = dict(client_id="other", token="stolen", generation=lease["generation"],
                    command_id="steal", command_seq=2, kind="terminate_job", payload={})
    assert client.post("/api/machines/ST01/commands", json=intruder).status_code == 403


# --- flow physics (cycle 2) ---

STACKING_POSE = {"travel": -500.0, "slew": 90.0, "luff": 0.0}


def height_at(world, x, z):
    domain = world.material
    i = int((x - domain.origin_x) / domain.cell)
    j = int((z - domain.origin_z) / domain.cell)
    return domain.heights[j * domain.nx + i]


def stacking_world(belt_speed=4.0, pose=STACKING_POSE, flow=3000.0):
    world = ready_world()
    op = Operator(world, "ST01")
    op.settle(dict(pose))
    op.send("set_belt", {"speed": belt_speed})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", dict(START_PAYLOAD, requested_flow_t_per_h=flow))
    return world, op


def test_stack_flows_at_requested_rate_when_belt_at_full_speed():
    world, op = stacking_world()
    before = world.state()["material"]["ledger"]["received_m3"]
    for _ in range(10):
        world.advance(1)
    delta = world.state()["material"]["ledger"]["received_m3"] - before
    assert delta == pytest.approx(3000.0 / 3600.0 * 10 / 0.85, rel=1e-9)
    record = only_job(world)
    assert record["actual_flow_t_per_h"] == pytest.approx(3000.0, rel=1e-9)
    assert record["completed_t"] == pytest.approx(delta * 0.85, rel=1e-9)
    assert record["reason"] is None
    assert record["status"] == "running"


def test_stack_flow_is_clamped_by_belt_capability_curve():
    world, op = stacking_world(belt_speed=2.0)
    before = world.state()["material"]["ledger"]["received_m3"]
    for _ in range(10):
        world.advance(1)
    delta = world.state()["material"]["ledger"]["received_m3"] - before
    assert delta == pytest.approx(1500.0 / 3600.0 * 10 / 0.85, rel=1e-9)
    record = only_job(world)
    assert record["actual_flow_t_per_h"] == pytest.approx(1500.0, rel=1e-9)
    assert record["reason"] == "CAPABILITY_LIMITED"


def test_stack_flow_zero_when_belt_not_running():
    world, op = stacking_world(belt_speed=0.0)
    for _ in range(10):
        world.advance(1)
    assert world.state()["material"]["ledger"]["received_m3"] == 0.0
    record = only_job(world)
    assert record["actual_flow_t_per_h"] == 0.0
    assert record["reason"] == "BELT_NOT_RUNNING"
    assert record["completed_t"] == 0.0


def test_outlet_outside_job_zone_stops_flow_with_reason():
    world, op = stacking_world(pose=dict(STACKING_POSE, slew=0.0))
    for _ in range(10):
        world.advance(1)
    assert world.state()["material"]["ledger"]["received_m3"] == 0.0
    record = only_job(world)
    assert record["reason"] == "OUT_OF_ZONE"
    assert record["actual_flow_t_per_h"] == 0.0


def test_outlet_outside_material_domain_stops_flow_with_reason():
    world, op = stacking_world(pose=dict(STACKING_POSE, slew=-90.0))
    for _ in range(10):
        world.advance(1)
    assert world.state()["material"]["ledger"]["received_m3"] == 0.0
    record = only_job(world)
    assert record["reason"] == "OUT_OF_DOMAIN"
    assert record["actual_flow_t_per_h"] == 0.0


def test_stack_lands_at_outlet_derived_from_current_pose():
    world, op = stacking_world()
    for _ in range(5):
        world.advance(1)
    outlet_z = -228.0 + 0.455 * 33.0
    assert height_at(world, -500.0, outlet_z) > 0.5
    assert height_at(world, -505.0, outlet_z) == pytest.approx(0.0, abs=1e-6)
    op.settle({"travel": -505.0})
    for _ in range(12):
        world.advance(1)
    assert height_at(world, -505.0, outlet_z) > 0.1


def test_paused_job_transfers_nothing():
    world, op = stacking_world()
    op.send("pause_job")
    before = world.state()["material"]["ledger"]["received_m3"]
    for _ in range(10):
        world.advance(1)
    assert world.state()["material"]["ledger"]["received_m3"] == before
    record = only_job(world)
    assert record["status"] == "paused"
    assert record["actual_flow_t_per_h"] == 0.0


def test_pause_clears_stale_flow_reason():
    world, op = stacking_world(belt_speed=0.0)
    world.advance(1)
    assert only_job(world)["reason"] == "BELT_NOT_RUNNING"
    op.send("pause_job")
    assert only_job(world)["reason"] is None


def test_advance_zero_with_running_job_is_harmless():
    world, op = stacking_world()
    world.advance(0)
    world.advance(0)
    record = only_job(world)
    assert record["status"] == "running"
    assert world.state()["material"]["ledger"]["received_m3"] == 0.0


def test_wheel_and_belt_spinning_alone_do_not_change_coal():
    world = ready_world()
    op = Operator(world, "ST01")
    op.settle(dict(STACKING_POSE))
    op.send("set_wheel", {"speed": 8.0})
    op.send("set_belt", {"speed": 4.0})
    for _ in range(20):
        world.advance(1)
    ledger = world.state()["material"]["ledger"]
    assert ledger["received_m3"] == 0.0
    assert ledger["output_m3"] == 0.0
    assert world.state()["jobs"] == {}


# --- acceptance: hard height cap and 160 m3 conservation (cycle 3) ---

def conservation_error(state):
    ledger, inventory = state["ledger"], state["inventory"]
    processed = ledger["initial_m3"] + ledger["received_m3"] + ledger["output_m3"]
    tolerance = max(1e-8, processed * 1e-9)
    identity = ledger["initial_m3"] + ledger["received_m3"] - ledger["output_m3"] - inventory["total_m3"]
    return abs(identity), tolerance


def grid_volume_m3(world):
    domain = world.material
    return sum(domain.heights) * domain.cell * domain.cell


def test_stationary_stack_hits_height_cap_and_refuses_without_counting():
    world, op = stacking_world()
    for _ in range(300):
        world.advance(1)
    record = only_job(world)
    assert record["reason"] == "RECEIVE_LIMITED"
    assert record["actual_flow_t_per_h"] < 1500.0  # heavily limited below the 3000 t/h request
    assert record["status"] == "running"
    domain = world.material
    assert max(domain.heights) <= 8.0 + 1e-9
    state = world.state()["material"]
    received = state["ledger"]["received_m3"]
    # the refused share of the requested integral never entered the ledger
    assert received < 0.9 * 3000.0 / 3600.0 * 300 / 0.85
    # every counted cubic metre is still on the grid
    assert grid_volume_m3(world) == pytest.approx(state["inventory"]["total_m3"], abs=1e-6)
    error, tolerance = conservation_error(state)
    assert error <= tolerance
    # once the core saturates, acceptance keeps running far below full flow
    # (the kernel tails creep asymptotically instead of a hard stop)
    before = received
    for _ in range(20):
        world.advance(1)
    assert world.state()["material"]["ledger"]["received_m3"] - before < 0.5 * 3000.0 / 3600.0 * 20 / 0.85


def test_sweeping_stack_reaches_160m3_and_conserves():
    world = ready_world()
    op = Operator(world, "ST01")
    op.settle({"travel": -620.0, "slew": 90.0, "luff": 0.0})
    op.send("set_belt", {"speed": 4.0})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", START_PAYLOAD)
    for k in range(41):
        op.send("set_targets", {"targets": {"travel": -620.0 + 4.0 * k}})
        for _ in range(4):
            world.advance(1)
    state = world.state()["material"]
    received = state["ledger"]["received_m3"]
    assert received >= 160.0
    domain = world.material
    assert min(domain.heights) >= 0.0
    assert max(domain.heights) <= 8.0 + 1e-9
    assert grid_volume_m3(world) == pytest.approx(state["inventory"]["total_m3"], abs=1e-4)
    error, tolerance = conservation_error(state)
    assert error <= tolerance
    record = only_job(world)
    assert record["completed_t"] == pytest.approx(received * 0.85, rel=1e-9)
    assert record["reason"] is None
    assert record["status"] == "running"
