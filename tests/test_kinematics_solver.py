import numpy as np
import pytest

from app.config.loader import load_loader_config
from app.core.kinematics_solver import KinematicsSolver


def solve(**overrides):
    _, geometry, _ = load_loader_config()
    axis_values = {
        "travel": 0.0,
        "slew": 0.0,
        "boom_luff": 10.0,
        "boom_extension": 0.0,
        "chute_rotate": 0.0,
    }
    axis_values.update(overrides)
    return KinematicsSolver().solve(geometry, axis_values)


def as_array(vec):
    return np.array(vec.to_list())


def test_travel_changes_all_key_points():
    start = solve(travel=0.0)
    moved = solve(travel=10.0)
    for point_name in (
        "base_position",
        "boom_root_position",
        "boom_tip_position",
        "chute_bottom_position",
        "discharge_point",
    ):
        delta = as_array(getattr(moved, point_name)) - as_array(getattr(start, point_name))
        assert delta == pytest.approx([10.0, 0.0, 0.0])


def test_slew_changes_boom_tip_xy():
    start = solve(slew=0.0)
    rotated = solve(slew=45.0)
    assert rotated.boom_tip_position.x != pytest.approx(start.boom_tip_position.x)
    assert rotated.boom_tip_position.y != pytest.approx(start.boom_tip_position.y)
    assert rotated.base_position.to_list() == pytest.approx(start.base_position.to_list())


def test_luff_changes_boom_tip_z():
    low = solve(boom_luff=0.0)
    high = solve(boom_luff=20.0)
    assert high.boom_tip_position.z > low.boom_tip_position.z


def test_extension_changes_boom_length():
    short = solve(boom_extension=0.0)
    long = solve(boom_extension=10.0)
    short_length = np.linalg.norm(as_array(short.boom_tip_position) - as_array(short.boom_root_position))
    long_length = np.linalg.norm(as_array(long.boom_tip_position) - as_array(long.boom_root_position))
    assert long_length - short_length == pytest.approx(10.0)
    assert short.fixed_boom_tip_position.to_list() == pytest.approx(long.fixed_boom_tip_position.to_list())


def test_chute_follows_boom_tip():
    result = solve(slew=30.0, boom_luff=20.0, boom_extension=5.0)
    assert result.chute_top_position.to_list() == pytest.approx(result.boom_tip_position.to_list())


def test_chute_rotate_only_changes_direction():
    start = solve(chute_rotate=0.0)
    rotated = solve(chute_rotate=30.0)
    assert rotated.chute_bottom_position.to_list() == pytest.approx(start.chute_bottom_position.to_list())
    assert rotated.discharge_point.to_list() == pytest.approx(start.discharge_point.to_list())
    assert rotated.chute_direction.to_list() != pytest.approx(start.chute_direction.to_list())


def test_chute_quarter_turn_boundary_poses_keep_attachment_points_fixed():
    baseline = solve(chute_rotate=0.0)
    directions = []

    # The configured axis range is [-180, 180], so 270 degrees is represented
    # by its equivalent -90 degree command.
    for angle in (0.0, 90.0, 180.0, -90.0):
        result = solve(chute_rotate=angle)
        assert result.chute_top_position.to_list() == pytest.approx(
            baseline.chute_top_position.to_list()
        )
        assert result.chute_bottom_position.to_list() == pytest.approx(
            baseline.chute_bottom_position.to_list()
        )
        assert result.discharge_point.to_list() == pytest.approx(
            baseline.discharge_point.to_list()
        )
        directions.append(tuple(round(value, 8) for value in result.chute_direction.to_list()))

    assert len(set(directions)) == 4


def test_discharge_point_exists():
    result = solve()
    assert len(result.discharge_point.to_list()) == 3


def test_render_key_points_are_exposed():
    result = solve(travel=7.0, slew=20.0, boom_luff=15.0)
    key_points = result.key_points()
    assert key_points["slew_center_position"].to_list() == pytest.approx(result.base_position.to_list())
    assert "fixed_boom_tip_position" in key_points
    assert "rail_origin_position" in key_points
    assert "rail_direction_point" in key_points
