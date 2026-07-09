import pytest

from app.config.loader import create_default_ship_loader
from app.core.simulation_world import SimulationWorld


def make_world() -> SimulationWorld:
    return SimulationWorld(create_default_ship_loader(), default_dt=0.1)


def test_sim_time_increases():
    world = make_world()
    snapshot = world.step()
    assert snapshot.sim_time == pytest.approx(0.1)


def test_pause_keeps_state():
    world = make_world()
    world.loader.set_axis_target("travel", 10.0, velocity=1.0)
    world.step(1.0)
    before = world.get_snapshot()
    world.pause()
    after = world.step(1.0)
    assert after.sim_time == pytest.approx(before.sim_time)
    assert after.axis_states["travel"].current == pytest.approx(before.axis_states["travel"].current)


def test_resume_continues_motion():
    world = make_world()
    world.loader.set_axis_target("travel", 10.0, velocity=1.0)
    world.pause()
    paused = world.step(1.0)
    world.resume()
    resumed = world.step(1.0)
    assert resumed.sim_time > paused.sim_time
    assert resumed.axis_states["travel"].current > paused.axis_states["travel"].current


def test_multiple_axes_update_together():
    world = make_world()
    world.loader.set_axis_target("travel", 10.0, velocity=1.0)
    world.loader.set_axis_target("slew", 45.0, velocity=5.0)
    snapshot = world.step(1.0)
    assert snapshot.axis_states["travel"].current == pytest.approx(1.0)
    assert snapshot.axis_states["slew"].current == pytest.approx(5.0)


def test_snapshot_has_all_required_fields():
    world = make_world()
    snapshot = world.get_snapshot()
    assert snapshot.loader_id == "SL01"
    assert set(snapshot.axis_states) >= {
        "travel",
        "slew",
        "boom_luff",
        "boom_extension",
        "chute_rotate",
    }
    assert set(snapshot.key_points) >= {
        "base_position",
        "boom_root_position",
        "boom_tip_position",
        "chute_top_position",
        "chute_bottom_position",
        "discharge_point",
    }
    assert snapshot.belt_state.running is False
    assert snapshot.vessel_motion.used_for_discharge_coordinate is False

