import pytest
from yard_motion.world import World


def test_target_travel_has_bounded_speed_and_stops_at_target():
    world = World()
    lease = world.acquire("ST01", "test")
    world.command("ST01", "test", lease["token"], lease["generation"],
                  "one", 1, "set_targets", {"targets": {"travel": -500}})
    for _ in range(1000):
        world.heartbeat("ST01", "test", lease["token"], lease["generation"])
        world.advance(.02)
        axis = world.state()["machines"]["ST01"]["axes"]["travel"]
        assert abs(axis["velocity"]) <= 2.000001
        assert axis["position"] <= -500.0
    assert axis["position"] == pytest.approx(-500)
    assert axis["velocity"] == 0
