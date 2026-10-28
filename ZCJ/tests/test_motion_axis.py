import pytest

from app.core.motion_axis import MotionAxis
from app.models.axis import AxisConfig


def make_axis(**overrides) -> MotionAxis:
    config = {
        "axis_id": "travel",
        "axis_type": "linear",
        "current": 0.0,
        "target": 0.0,
        "velocity": 2.0,
        "min_value": -20.0,
        "max_value": 20.0,
        "tolerance": 0.001,
    }
    config.update(overrides)
    return MotionAxis(AxisConfig.model_validate(config))


def test_linear_axis_move_to_target():
    axis = make_axis()
    axis.set_target(10.0)
    axis.update(1.0)
    assert axis.current == pytest.approx(2.0)
    assert axis.running is True
    assert axis.at_target is False


def test_axis_does_not_overshoot():
    axis = make_axis(velocity=8.0)
    axis.set_target(10.0)
    axis.update(2.0)
    assert axis.current == pytest.approx(10.0)
    assert axis.running is False
    assert axis.at_target is True


def test_axis_stop():
    axis = make_axis()
    axis.set_target(10.0)
    axis.update(1.0)
    axis.stop()
    axis.update(1.0)
    assert axis.current == pytest.approx(2.0)
    assert axis.running is False


def test_axis_disabled():
    axis = make_axis(enabled=False)
    axis.set_target(10.0)
    axis.start()
    axis.update(1.0)
    assert axis.current == pytest.approx(0.0)
    assert axis.running is False


def test_axis_target_limit():
    axis = make_axis()
    with pytest.raises(ValueError):
        axis.set_target(30.0)


def test_rotary_axis_move():
    axis = make_axis(
        axis_id="slew",
        axis_type="rotary",
        current=45.0,
        target=45.0,
        velocity=15.0,
        min_value=-180.0,
        max_value=180.0,
    )
    axis.set_target(-30.0)
    axis.update(1.0)
    assert axis.current == pytest.approx(30.0)
    assert axis.running is True

