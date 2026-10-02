from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import json
from pathlib import Path

import pytest

from yard_motion.errors import MotionError
from yard_motion.world import World
from test_stacking import Operator, START_PAYLOAD, ready_world, stacking_world


def test_same_zone_competition_is_atomic_and_pause_keeps_ownership():
    world = ready_world()
    operators = [Operator(world, "ST01"), Operator(world, "RC01")]
    barrier = Barrier(2)

    def start(op):
        barrier.wait()
        try:
            op.send("start_job", START_PAYLOAD)
            return "accepted"
        except MotionError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(start, operators))
    assert sorted(outcomes) == ["ZONE_BUSY", "accepted"]
    winner, loser = (operators[outcomes.index(value)] for value in ("accepted", "ZONE_BUSY"))
    winner.send("pause_job")
    occupancy = world.state()["zone_occupancy"]["north-12"]
    assert occupancy["machine_id"] == winner.machine_id
    with pytest.raises(MotionError, match=winner.machine_id):
        loser.send("start_job", START_PAYLOAD)
    winner.send("terminate_job")
    assert world.state()["zone_occupancy"]["north-12"] is None
    loser.send("start_job", START_PAYLOAD)
    assert world.state()["zone_occupancy"]["north-12"]["machine_id"] == loser.machine_id


def test_timeout_pauses_then_releases_only_after_stopping_and_resume_reclaims_zone():
    now = [0.0]
    world = World(clock=lambda: now[0])
    world.init_material("empty")
    st = Operator(world, "ST01", "old-client")
    st.send("set_belt", {"speed": 4})
    for _ in range(10):
        world.advance(1)
    st.send("start_job", dict(START_PAYLOAD, target_t=2))
    now[0] = 4.0
    state = world.state()
    job_id = next(iter(state["jobs"]))
    assert state["jobs"][job_id]["status"] == "paused"
    assert state["jobs"][job_id]["reason"] == "CONNECTION_TIMEOUT"
    assert state["machines"]["ST01"]["control"]["state"] == "releasing"
    assert state["zone_occupancy"]["north-12"]["machine_id"] == "ST01"
    rc = Operator(world, "RC01", "new-client")
    with pytest.raises(MotionError) as held:
        rc.send("start_job", START_PAYLOAD)
    assert held.value.code == "ZONE_BUSY"
    for _ in range(100):
        world.advance(.1)
    state = world.state()
    assert state["machines"]["ST01"]["control"] is None
    assert state["zone_occupancy"]["north-12"] is None
    rc.send("start_job", START_PAYLOAD)
    new_st = Operator(world, "ST01", "new-client")
    assert world.state()["jobs"][job_id]["status"] == "paused"
    with pytest.raises(MotionError) as busy:
        new_st.send("resume_job")
    assert busy.value.code == "ZONE_BUSY"
    rc.send("terminate_job")
    new_st.send("resume_job")
    assert world.state()["jobs"][job_id]["status"] == "running"
    assert world.state()["jobs"][job_id]["target_t"] == 2


@pytest.mark.parametrize("end", ["terminate_job", "finish_job", "completed", "reset"])
def test_terminal_states_release_zone_and_preserve_coal(end):
    world, st = stacking_world()
    st.send("terminate_job")
    st.send("start_job", dict(START_PAYLOAD, target_t=.01))
    if end == "completed":
        world.advance(.1)
    else:
        before = world.state()["material"]
        st.send(end)
        assert world.state()["material"] == before
    assert world.state()["zone_occupancy"]["north-12"] is None
    rc = Operator(world, "RC01")
    rc.send("start_job", START_PAYLOAD)


@pytest.mark.parametrize("kind,payload", [("stop", {}), ("estop", {}),
                                           ("set_belt", {"speed": 0}), ("set_wheel", {"speed": 0})])
def test_stop_protection_pauses_and_keeps_zone_until_explicit_finish(kind, payload):
    world, op = stacking_world()
    op.send(kind, payload)
    state = world.state()
    assert next(iter(state["jobs"].values()))["status"] == "paused"
    assert state["zone_occupancy"]["north-12"]["machine_id"] == "ST01"
    if kind == "estop":
        op.send("clear_estop")
        assert next(iter(world.state()["jobs"].values()))["status"] == "paused"


def test_pilot_rejects_multiple_zone_names_on_shared_material_grid():
    config = json.loads((Path(__file__).parents[1] / "config/material.json").read_text(encoding="utf-8"))
    config["job_zones"]["alias"] = dict(config["job_zones"]["north-12"])
    with pytest.raises(ValueError, match="one job zone"):
        World(material_config=config)
