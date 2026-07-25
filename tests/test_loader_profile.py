import json

import pytest
from pydantic import ValidationError

from app.config.loader import DEFAULT_CONFIG_PATH, load_loader_profile
from app.models.loader_config import LoaderProfile


def test_default_profile_is_sl15_and_matches_cad_values():
    profile = load_loader_profile()
    assert profile.variant_id == "SL15"
    assert profile.loader_id == "SL15"
    assert profile.coordinate_system == "WORLD_Z_UP_METERS"
    assert profile.engineering.rated_capacity_tph == pytest.approx(8000.0)
    assert profile.engineering.max_capacity_tph == pytest.approx(9200.0)
    assert profile.engineering.rail_gauge_m == pytest.approx(23.0)
    assert profile.engineering.wheel_base_m == pytest.approx(22.0)
    assert profile.engineering.outreach_min_m == pytest.approx(16.5)
    assert profile.engineering.outreach_max_m == pytest.approx(37.75)
    assert profile.engineering.boom_extension_travel_m == pytest.approx(21.25)
    assert profile.geometry.boom_extension_max_m == pytest.approx(21.25)
    assert profile.geometry.chute_length_m == pytest.approx(12.6)
    assert profile.visual.asset_revision == "sl15-procedural-r4"
    assert profile.visual.chute_branch_spread_m == pytest.approx(1.65)


def test_sl15_axis_limits_and_speed_limits_are_enforced():
    profile = load_loader_profile()
    expected_limits = {
        "travel": (-100.0, 100.0, 0.5),
        "slew": (-35.0, 215.0, 1.02),
        "boom_luff": (-10.0, 24.0, 2.0),
        "boom_extension": (0.0, 21.25, 0.1),
        "chute_rotate": (-180.0, 180.0, 12.0),
    }
    for axis_id, (minimum, maximum, max_velocity) in expected_limits.items():
        axis = profile.axes[axis_id]
        assert axis.min_value == pytest.approx(minimum)
        assert axis.max_value == pytest.approx(maximum)
        assert axis.max_velocity == pytest.approx(max_velocity)


def test_profile_rejects_extension_range_that_disagrees_with_sl15():
    raw = json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
    raw["geometry"]["boom_extension_max_m"] = 20.0
    raw["axes"] = {
        axis_id: {
            "axis_id": axis_id,
            "axis_type": axis["type"],
            "current": axis["current"],
            "target": axis["current"],
            "velocity": axis["velocity"],
            "max_velocity": axis["max_velocity"],
            "min_value": axis["min_value"],
            "max_value": 20.0 if axis_id == "boom_extension" else axis["max_value"],
            "tolerance": axis["tolerance"],
        }
        for axis_id, axis in raw["axes"].items()
    }
    with pytest.raises(ValidationError, match="extension range"):
        LoaderProfile.model_validate(raw)
