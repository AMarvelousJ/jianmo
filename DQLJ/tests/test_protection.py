import copy

import pytest

from yard_motion.world import MotionError, World


class Operator:
    def __init__(self):
        self.now = 0.
        self.world = World(clock=lambda: self.now)
        self.seq = 0
        self.lease = self.world.acquire("ST01", "operator")

    def send(self, kind, payload=None, seq=None):
        self.seq += 1
        return self.world.command("ST01", "operator", self.lease["token"], self.lease["generation"],
                                  str(self.seq), seq or self.seq, kind, payload or {})

    def tick(self, seconds, renew=True):
        for _ in range(round(seconds / .02)):
            self.now += .02
            if renew:
                self.world.heartbeat("ST01", "operator", self.lease["token"], self.lease["generation"])
            self.world.advance(.02)

    def state(self):
        return self.world.state()["machines"]["ST01"]


def test_jog_cancels_only_its_axis_and_timeout_stops_without_resuming_target():
    op = Operator()
    op.send("set_targets", {"targets": {"travel": -490, "slew": 20}})
    op.tick(1)
    op.send("jog", {"axis": "travel", "direction": -1, "speed": 2})
    assert op.state()["axes"]["travel"]["target"] is None
    op.tick(6)
    assert op.state()["axes"]["travel"]["mode"] == "idle"
    assert op.state()["axes"]["travel"]["velocity"] == 0
    assert op.state()["axes"]["slew"]["position"] == pytest.approx(20)


def test_disconnect_releases_only_after_all_drives_stop():
    op = Operator()
    op.send("set_targets", {"targets": {"travel": -450}})
    op.send("set_wheel", {"speed": 8})
    op.tick(4)
    op.tick(3.1, renew=False)
    assert op.state()["control"]["state"] == "releasing"
    with pytest.raises(MotionError, match="控制权"):
        op.world.acquire("ST01", "other")
    op.tick(5, renew=False)
    assert op.state()["control"] is None
    assert not op.state()["running"]
    lease = op.world.acquire("ST01", "other")
    assert lease["generation"] > op.lease["generation"]


def test_reset_does_not_clear_estop_and_clear_does_not_resume():
    op = Operator()
    op.send("set_targets", {"targets": {"travel": -500}})
    op.tick(1)
    op.send("estop")
    assert op.state()["axes"]["travel"]["velocity"] == 0
    with pytest.raises(MotionError, match="急停"):
        op.send("set_belt", {"speed": 1})
    op.send("reset")
    assert op.state()["axes"]["travel"]["position"] == -510
    assert op.state()["estop_latched"]
    op.send("clear_estop")
    assert not op.state()["running"]


@pytest.mark.parametrize("value", [999, float("nan"), float("inf"), True])
def test_invalid_target_is_atomic(value):
    op = Operator()
    before = copy.deepcopy(op.state()["axes"])
    with pytest.raises(MotionError):
        op.send("set_targets", {"targets": {"travel": -500, "luff": value}})
    assert op.state()["axes"] == before


def test_retry_is_idempotent_and_old_jog_cannot_revive():
    op = Operator()
    first = op.send("jog", {"axis": "travel", "direction": 1, "speed": 1})
    op.send("stop_jog")
    retry = op.world.command("ST01", "operator", op.lease["token"], op.lease["generation"],
                             "1", 1, "jog", {"axis": "travel", "direction": 1, "speed": 1})
    assert retry == first
    assert op.state()["axes"]["travel"]["mode"] == "idle"
    with pytest.raises(MotionError):
        op.world.command("ST01", "operator", op.lease["token"], op.lease["generation"],
                         "unknown-old", 1, "jog", {"axis": "travel", "direction": 1, "speed": 1})


def test_drive_phase_and_restart_are_independent_of_other_machines():
    op = Operator()
    op.send("set_wheel", {"speed": 4})
    op.send("set_belt", {"speed": 2})
    op.tick(3)
    assert op.state()["wheel"]["distance"] == pytest.approx(48)
    assert op.state()["belt"]["distance"] == pytest.approx(4)
    assert op.world.state()["machines"]["RC01"]["wheel"]["speed"] == 0
    new = World()
    assert new.instance != op.world.instance
    assert all(not m["running"] and m["control"] is None for m in new.state()["machines"].values())


def test_changing_target_to_current_position_does_not_bypass_deceleration():
    op = Operator()
    op.send("set_targets", {"targets": {"travel": -450}})
    op.tick(4)
    axis = op.state()["axes"]["travel"]
    goal = axis["position"]
    old_velocity = axis["velocity"]
    op.send("set_targets", {"targets": {"travel": goal}})
    op.tick(.02)
    assert abs(op.state()["axes"]["travel"]["velocity"] - old_velocity) <= .010001
    op.tick(12)
    assert op.state()["axes"]["travel"]["position"] == pytest.approx(goal, abs=.001)
    assert op.state()["axes"]["travel"]["velocity"] == 0


def test_short_target_and_limit_approach_preserve_acceleration_bounds():
    op = Operator()
    for goal in (-509.99, -425., -625.):
        op.send("set_targets", {"targets": {"travel": goal}})
        old_velocity = op.state()["axes"]["travel"]["velocity"]
        for _ in range(6000):
            op.tick(.02)
            axis = op.state()["axes"]["travel"]
            assert abs(axis["velocity"]-old_velocity) <= .01001
            assert -625 <= axis["position"] <= -425
            old_velocity = axis["velocity"]
            if axis["mode"] == "idle":
                break
        assert axis["position"] == pytest.approx(goal, abs=.001)
        assert axis["velocity"] == 0
