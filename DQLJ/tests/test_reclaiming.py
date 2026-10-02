import pytest

from yard_motion.world import World
from test_stacking import Operator, START_PAYLOAD


def reclaim_world(wheel=8.0, belt=4.0):
    world = World(clock=lambda: 0.0)
    world.init_material("preset")
    op = Operator(world, "RC01", "reclaim-test")
    op.settle({"travel": -365.0, "slew": 90.0, "luff": -8.0})
    op.send("set_wheel", {"speed": wheel})
    op.send("set_belt", {"speed": belt})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", START_PAYLOAD)
    return world, op


def test_reclaim_transfers_only_actual_coal_and_preserves_total_balance():
    world, op = reclaim_world()
    initial = world.state()["material"]["inventory"]["total_m3"]
    for _ in range(100):
        world.advance(.1)
    state = world.state()
    material = state["material"]
    job = next(iter(state["jobs"].values()))
    assert material["ledger"]["output_m3"] > 0
    assert material["ledger"]["received_m3"] == 0
    assert initial - material["ledger"]["output_m3"] == pytest.approx(material["inventory"]["total_m3"], abs=1e-8)
    assert job["role"] == "reclaiming"
    assert job["completed_t"] == pytest.approx(material["ledger"]["output_m3"]*.85)
    assert job["actual_flow_t_per_h"] <= 3000
    assert min(world.material.heights) >= 0


@pytest.mark.parametrize("wheel,belt,reason", [(0,4,"WHEEL_NOT_RUNNING"),(8,0,"BELT_NOT_RUNNING")])
def test_reclaim_requires_both_drives(wheel,belt,reason):
    world,op=reclaim_world(wheel,belt)
    for _ in range(5): world.advance(.1)
    state=world.state()
    job=next(iter(state["jobs"].values()))
    assert state["material"]["ledger"]["output_m3"]==0
    assert job["status"]=="running" and job["reason"]==reason


def test_empty_or_unreachable_coal_waits_without_discarding_inventory():
    world,op=reclaim_world()
    op.send("terminate_job")
    world.init_material("empty",confirm=True)
    op.send("start_job",START_PAYLOAD)
    world.advance(.1)
    state=world.state();job=list(state["jobs"].values())[-1]
    assert job["status"]=="running" and job["reason"]=="NO_CONTACT"
    assert state["material"]["ledger"]["output_m3"]==0


def test_twenty_cubic_metres_reclaimed_with_nonnegative_conserved_stock():
    world,op=reclaim_world()
    for n in range(1500):
        world.advance(.1)
        if world.state()["material"]["ledger"]["output_m3"]>=20: break
    state=world.state()["material"]
    assert state["ledger"]["output_m3"]>=20
    assert state["ledger"]["initial_m3"]-state["ledger"]["output_m3"]==pytest.approx(state["inventory"]["total_m3"],abs=1e-8)
    assert min(world.material.heights)>=0
    assert state["relaxation"]["iteration_budget"]>0
    assert state["relaxation"]["time_budget_s"]>0


def test_estop_pauses_material_and_clear_does_not_resume_old_job():
    world,op=reclaim_world()
    world.advance(.1)
    before=world.state()["material"]["ledger"]["output_m3"]
    op.send("estop")
    job=next(iter(world.state()["jobs"].values()))
    assert job["status"]=="paused" and job["actual_flow_t_per_h"]==0
    op.send("clear_estop")
    op.send("set_wheel",{"speed":8})
    op.send("set_belt",{"speed":4})
    for _ in range(10): world.advance(.1)
    assert world.state()["material"]["ledger"]["output_m3"]==before
