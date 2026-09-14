import time

from fastapi.testclient import TestClient

from app.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plc_status_endpoint_is_safe_by_default():
    client = TestClient(app)
    response = client.get("/api/plc/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is False
    assert body["connected"] is False
    assert body["plc_ip"] == "10.60.97.40"
    assert body["slot"] == 0


def test_state_endpoint_returns_snapshot():
    client = TestClient(app)
    response = client.get("/api/state")
    assert response.status_code == 200
    body = response.json()
    assert body["loader_id"] == "SL15"
    assert body["sim_paused"] is False
    assert "axis_states" in body
    assert "key_points" in body
    assert "fixed_boom_tip_position" in body["key_points"]


def test_unity_clock_client_advances_simulation_and_prevents_double_step():
    client = TestClient(app)
    client.post("/api/simulation/reset")
    client_id = "unity-api-test"
    try:
        registered = client.put(
            f"/api/simulation/clock/clients/{client_id}",
            json={"client_name": "unity"},
        )
        assert registered.status_code == 200
        assert registered.json()["active_clients"] >= 1

        before = client.get("/api/state").json()["sim_time"]
        deadline = time.monotonic() + 1.0
        after = before
        while after <= before and time.monotonic() < deadline:
            time.sleep(0.03)
            after = client.get("/api/state").json()["sim_time"]
        assert after > before

        legacy_step = client.post("/api/simulation/step", json={"dt": 10.0})
        assert legacy_step.status_code == 200
        assert legacy_step.json()["sim_time"] < after + 1.0
    finally:
        released = client.delete(f"/api/simulation/clock/clients/{client_id}")
        assert released.status_code == 200
        assert released.json()["active_clients"] == 0
        client.post("/api/simulation/reset")


def test_luff_and_extension_targets_move_after_step():
    client = TestClient(app)
    client.post("/api/simulation/reset")

    luff_response = client.post(
        "/api/axis/boom_luff/target",
        json={"target": 20.0, "velocity": 2.0},
    )
    assert luff_response.status_code == 200
    extension_response = client.post(
        "/api/axis/boom_extension/target",
        json={"target": 10.0, "velocity": 0.1},
    )
    assert extension_response.status_code == 200

    before = client.get("/api/state").json()
    step_response = client.post("/api/simulation/step", json={"dt": 1.0})
    assert step_response.status_code == 200
    after = step_response.json()

    assert before["axis_states"]["boom_luff"]["target"] == 20.0
    assert before["axis_states"]["boom_extension"]["target"] == 10.0
    assert after["axis_states"]["boom_luff"]["current"] > before["axis_states"]["boom_luff"]["current"]
    assert after["axis_states"]["boom_extension"]["current"] > before["axis_states"]["boom_extension"]["current"]
    assert after["key_points"]["boom_tip_position"] != before["key_points"]["boom_tip_position"]
    client.post("/api/simulation/reset")


def test_loader_config_endpoint_returns_sl15_profile():
    client = TestClient(app)
    response = client.get("/api/loader/config")
    assert response.status_code == 200
    body = response.json()
    assert body["variant_id"] == "SL15"
    assert body["loader_id"] == "SL15"
    assert body["engineering"]["rail_gauge_m"] == 23.0
    assert body["engineering"]["wheel_base_m"] == 22.0
    assert body["engineering"]["outreach_max_m"] == 37.75
    assert body["engineering"]["boom_extension_travel_m"] == 21.25
    assert body["geometry"]["boom_extension_max_m"] == 21.25
    assert body["geometry"]["chute_length_m"] == 12.6
    assert body["visual"]["asset_revision"] == "sl15-procedural-r4"
    assert body["visual"]["chute_ladder_rungs"] == 15


def test_axis_command_rejects_speed_above_sl15_limit():
    client = TestClient(app)
    client.post("/api/simulation/reset")
    response = client.post(
        "/api/axis/boom_extension/target",
        json={"target": 1.0, "velocity": 0.11},
    )
    assert response.status_code == 400
    assert "max_velocity" in response.json()["detail"]


def test_scene_endpoint_returns_default_scene():
    client = TestClient(app)
    response = client.get("/api/scene")
    assert response.status_code == 200
    body = response.json()
    assert "vessels" in body
    assert len(body["vessels"]) >= 1
    assert len(body["vessels"][0]["holds"]) >= 1
    assert body["vessels"][0]["cover_type"] in {"horizontal", "vertical", "none"}


def test_scene_endpoint_updates_variable_holds():
    client = TestClient(app)
    original_scene = client.get("/api/scene").json()
    scene = {
        "vessels": [
            {
                "id": "Dynamic-Vessel",
                "position": [5.0, 18.0, 1.5],
                "length_m": 40.0,
                "width_m": 7.0,
                "height_m": 3.0,
                "side": "right",
                "holds": [
                    {
                        "id": "H1",
                        "center_offset_m": -8.0,
                        "length_m": 7.0,
                        "width_m": 5.0,
                        "fill_level": 0.25,
                    },
                    {
                        "id": "H2",
                        "center_offset_m": 4.0,
                        "length_m": 8.0,
                        "width_m": 5.2,
                        "fill_level": 0.7,
                    },
                    {
                        "id": "H3",
                        "center_offset_m": 14.0,
                        "length_m": 6.5,
                        "width_m": 5.0,
                        "fill_level": 0.1,
                    },
                ],
            }
        ]
    }
    update_response = client.put("/api/scene", json=scene)
    assert update_response.status_code == 200
    updated_scene = update_response.json()
    assert updated_scene["vessels"][0]["id"] == scene["vessels"][0]["id"]
    assert updated_scene["vessels"][0]["cover_type"] == "none"

    get_response = client.get("/api/scene")
    assert get_response.status_code == 200
    assert len(get_response.json()["vessels"][0]["holds"]) == 3

    restore_response = client.put("/api/scene", json=original_scene)
    assert restore_response.status_code == 200


def test_scene_endpoint_accepts_hatch_covers():
    client = TestClient(app)
    original_scene = client.get("/api/scene").json()
    scene = {
        "vessels": [
            {
                "id": "Cover-Test",
                "position": [0.0, 12.0, 1.5],
                "length_m": 34.0,
                "width_m": 7.2,
                "height_m": 3.0,
                "side": "right",
                "cover_type": "vertical",
                "holds": [
                    {
                        "id": "C1",
                        "center_offset_m": -5.0,
                        "length_m": 7.0,
                        "width_m": 5.2,
                        "fill_level": 0.2,
                        "cover": {
                            "length_m": 2.3,
                            "width_m": 5.0,
                            "thickness_m": 0.24,
                        },
                    },
                    {
                        "id": "C2",
                        "center_offset_m": 6.0,
                        "length_m": 8.5,
                        "width_m": 5.6,
                        "fill_level": 0.6,
                        "cover": {
                            "length_m": 2.6,
                            "width_m": 5.4,
                            "thickness_m": 0.28,
                        },
                    },
                ],
            }
        ]
    }
    response = client.put("/api/scene", json=scene)
    assert response.status_code == 200
    body = response.json()
    assert body["vessels"][0]["cover_type"] == "vertical"
    assert body["vessels"][0]["holds"][0]["cover"]["length_m"] == 2.3
    assert body["vessels"][0]["holds"][1]["cover"]["thickness_m"] == 0.28

    restore_response = client.put("/api/scene", json=original_scene)
    assert restore_response.status_code == 200
