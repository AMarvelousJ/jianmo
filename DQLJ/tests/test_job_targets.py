import pytest

from yard_motion.errors import MotionError
from test_stacking import stacking_world, START_PAYLOAD, Operator
from test_reclaiming import reclaim_world


def current_job(world):
    return list(world.state()["jobs"].values())[-1]


@pytest.mark.parametrize("role", ["stack", "reclaim"])
@pytest.mark.parametrize("dt", [.02, .1, 1.0])
def test_target_finishes_at_actual_tonnage_without_stopping_drives(role, dt):
    world, op = stacking_world() if role == "stack" else reclaim_world()
    op.send("terminate_job")
    op.send("start_job", dict(START_PAYLOAD, target_t=.237))
    for _ in range(1000):
        world.advance(dt)
        if current_job(world)["status"] == "completed":
            break
    job = current_job(world)
    assert job["status"] == "completed"
    assert job["completed_t"] == pytest.approx(.237, abs=1e-9)
    assert job["remaining_t"] <= 1e-9
    assert job["actual_flow_t_per_h"] == 0
    material = world.state()["material"]
    key = "received_m3" if role == "stack" else "output_m3"
    assert material["ledger"][key] * .85 == pytest.approx(.237, abs=1e-9)
    machine = world.state()["machines"][op.machine_id]
    assert machine["belt"]["speed"] > 0
    if role == "reclaim":
        assert machine["wheel"]["speed"] > 0
    ledger = dict(material["ledger"])
    for _ in range(5):
        world.advance(dt)
    assert world.state()["material"]["ledger"] == ledger


def test_pause_preserves_target_and_progress_new_job_resets_counter():
    world, op = stacking_world()
    op.send("terminate_job")
    op.send("start_job", dict(START_PAYLOAD, target_t=2))
    world.advance(.1)
    op.send("pause_job")
    paused = current_job(world)
    world.advance(1)
    assert current_job(world) == paused
    assert paused["remaining_t"] == pytest.approx(2 - paused["completed_t"])
    op.send("resume_job")
    world.advance(.1)
    assert current_job(world)["completed_t"] > paused["completed_t"]
    op.send("terminate_job")
    op.send("start_job", dict(START_PAYLOAD, target_t=3))
    assert current_job(world)["completed_t"] == 0
    assert current_job(world)["remaining_t"] == 3


@pytest.mark.parametrize("target", [0, -1, True, "1"])
def test_invalid_target_is_rejected_without_creating_job(target):
    world, op = stacking_world()
    op.send("terminate_job")
    count = len(world.state()["jobs"])
    with pytest.raises(MotionError):
        op.send("start_job", dict(START_PAYLOAD, target_t=target))
    assert len(world.state()["jobs"]) == count


def test_explicit_finish_reports_shortfall_and_retains_uncontacted_coal():
    world, op = reclaim_world()
    op.send("terminate_job")
    op.settle({"travel": -345, "slew": 0, "luff": 0})
    op.send("start_job", dict(START_PAYLOAD, target_t=10))
    world.advance(.1)
    assert current_job(world)["status"] == "running"
    assert current_job(world)["reason"] == "NO_CONTACT"
    before = world.state()["material"]
    op.send("finish_job")
    job = current_job(world)
    assert job["status"] == "incomplete"
    assert job["remaining_t"] == 10
    assert job["actual_flow_t_per_h"] == 0
    report = job["finish_report"]
    assert report["scope"] == "current_pose_full_revolution"
    assert report["contactable_m3"] == 0
    assert report["uncontacted_m3"] == pytest.approx(before["inventory"]["total_m3"])
    assert report["whole_workspace_unreachable_m3"] is None
    assert world.state()["material"] == before
    # A caller cannot mutate the retained report through its returned snapshot.
    report["uncontacted_m3"] = -1
    assert current_job(world)["finish_report"]["uncontacted_m3"] >= 0
    op.send("start_job", dict(START_PAYLOAD, target_t=1))
    assert current_job(world)["completed_t"] == 0


def test_target_counts_only_actual_material_and_explicit_stack_finish_keeps_stock():
    world, op = stacking_world(belt_speed=0)
    op.send("terminate_job")
    op.send("start_job", dict(START_PAYLOAD, target_t=.1))
    for _ in range(5):
        world.advance(1)
    job = current_job(world)
    assert job["status"] == "running"
    assert job["completed_t"] == 0
    assert job["remaining_t"] == .1
    before = world.state()["material"]
    result = op.send("finish_job", command_id="finish-once")
    replay = world.command(op.machine_id, *op.creds, "finish-once", op.seq, "finish_job", {})
    assert replay == result
    assert current_job(world)["status"] == "incomplete"
    assert current_job(world)["finish_report"]["scope"] == "inventory_only"
    assert world.state()["material"] == before


def test_history_remains_bounded_while_oldest_job_is_still_active():
    from test_stacking import ready_world

    world = ready_world()
    st = Operator(world, "ST01", "history-test")
    st.send("start_job", START_PAYLOAD)
    active_id = current_job(world)["job_id"]
    # Release a stopped machine's control/zone, retaining its paused progress.
    world.release("ST01", *st.creds)
    assert world.state()["zone_occupancy"]["north-12"] is None
    op = Operator(world, "RC01", "history-test")
    for _ in range(520):
        op.send("start_job", START_PAYLOAD)
        op.send("terminate_job")
    jobs = world.state()["jobs"]
    assert len(jobs) <= 512
    assert jobs[active_id]["status"] == "paused"
