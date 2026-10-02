import pytest
import json
import hashlib
from pathlib import Path
import subprocess
import sys

from yard_motion.world import World
from test_stacking import Operator, START_PAYLOAD, STACKING_POSE
from yard_motion.errors import MotionError


def test_pause_saves_shape_ledger_and_progress_restart_stays_stopped(tmp_path):
    path = tmp_path / "material.json"
    world = World(clock=lambda: 0.0, snapshot_path=path)
    world.init_material("empty")
    op = Operator(world, "ST01")
    op.settle(STACKING_POSE)
    op.send("set_belt", {"speed": 4})
    for _ in range(10):
        world.advance(1)
    op.send("start_job", dict(START_PAYLOAD, target_t=2))
    world.advance(.2)
    op.send("pause_job")
    before = world.material_grid()
    job_id = next(iter(world.state()["jobs"]))
    restarted = World(clock=lambda: 0.0, snapshot_path=path)
    state = restarted.state()
    assert restarted.material_grid()["grid"] == before["grid"]
    assert state["material"]["ledger"] == before["material"]["ledger"]
    assert state["server_instance_id"] != before["server_instance_id"]
    job = state["jobs"][job_id]
    assert job["status"] == "stopped"
    assert job["target_t"] == 2
    assert job["completed_t"] > 0
    assert job["remaining_t"] == pytest.approx(2 - job["completed_t"])
    assert all(m["control"] is None and not m["running"] for m in state["machines"].values())
    assert state["zone_occupancy"]["north-12"] is None
    assert op.creds[1] not in path.read_text(encoding="utf-8")
    before_ledger = dict(state["material"]["ledger"])
    restarted.advance(.2)
    assert restarted.state()["material"]["ledger"] == before_ledger
    with pytest.raises(MotionError):
        restarted.command("ST01", *op.creds, "old-token", 999, "resume_job", {})
    operator = Operator(restarted, "ST01", "new-client")
    operator.settle(STACKING_POSE)
    operator.send("set_belt", {"speed": 4})
    for _ in range(10):
        restarted.advance(1)
    operator.send("resume_job")
    assert restarted.state()["jobs"][job_id]["status"] == "running"
    assert restarted.state()["zone_occupancy"]["north-12"]["machine_id"] == "ST01"
    for _ in range(100):
        restarted.advance(.1)
        if restarted.state()["jobs"][job_id]["status"] == "completed":
            break
    assert restarted.state()["jobs"][job_id]["completed_t"] == pytest.approx(2, abs=1e-9)
    assert restarted.state()["jobs"][job_id]["status"] == "completed"
    assert restarted.state()["material"]["ledger"]["received_m3"] * .85 == pytest.approx(2, abs=1e-9)


def test_periodic_snapshot_leaves_at_most_one_second_of_unflushed_progress(tmp_path):
    path = tmp_path / "material.json"
    world = World(clock=lambda: 0.0, snapshot_path=path)
    world.init_material("empty")
    start = world.state()["persistence"]["last_saved_snapshot_seq"]
    world.advance(.8)
    assert world.state()["persistence"]["last_saved_snapshot_seq"] == start
    world.advance(.2)
    saved = world.state()["persistence"]
    assert saved["last_saved_snapshot_seq"] == world.state()["snapshot_seq"]
    world.advance(.4)
    restarted = World(clock=lambda: 0.0, snapshot_path=path)
    assert restarted.state()["sim_time"] == pytest.approx(1)
    assert world.state()["sim_time"] - restarted.state()["sim_time"] < 1


def test_corrupt_primary_uses_valid_backup_and_preserves_evidence(tmp_path):
    path = tmp_path / "material.json"
    world = World(clock=lambda: 0.0, snapshot_path=path)
    world.init_material("empty")
    world.init_material("preset", confirm=True)
    path.write_text("{torn", encoding="utf-8")
    restarted = World(snapshot_path=path)
    status = restarted.state()["persistence"]
    assert status["loaded_from"] == "backup"
    assert status["recovery_warning"]
    assert not status["recovery_required"]
    assert restarted.state()["material"]["scene"] == "empty"
    assert list(tmp_path.glob("material.json.rejected-*"))
    assert path.read_text(encoding="utf-8") == "{torn"
    restarted.advance(1)
    assert json.loads(path.read_text(encoding="utf-8"))["format"] == "dqlj-material-snapshot-v1"


def test_no_valid_archive_blocks_material_writes_without_destroying_files(tmp_path):
    path = tmp_path / "material.json"
    path.write_text("corrupt", encoding="utf-8")
    world = World(clock=lambda: 0.0, snapshot_path=path)
    assert world.state()["persistence"]["recovery_required"]
    assert world.state()["persistence"]["error"]
    with pytest.raises(MotionError) as refused:
        world.init_material("empty", confirm=True)
    assert refused.value.code == "PERSISTENCE_RECOVERY_REQUIRED"
    op = Operator(world, "ST01")
    with pytest.raises(MotionError):
        op.send("start_job", START_PAYLOAD)
    world.advance(1)
    assert path.read_text(encoding="utf-8") == "corrupt"


def test_save_failure_is_visible_and_does_not_claim_a_success(tmp_path):
    parent = tmp_path / "not-a-directory"
    parent.write_text("blocked", encoding="utf-8")
    world = World(snapshot_path=parent / "material.json")
    world.init_material("empty")
    state = world.state()["persistence"]
    assert "SNAPSHOT_SAVE_FAILED" in state["error"]
    assert state["last_saved_at_utc"] is None
    assert state["last_saved_snapshot_seq"] is None


@pytest.mark.parametrize("damage", ["checksum", "configuration", "ledger", "job_target"])
def test_checksums_configuration_and_semantic_validation_prevent_unsafe_restore(tmp_path, damage):
    path = tmp_path / "material.json"
    world = World(clock=lambda: 0.0, snapshot_path=path)
    world.init_material("empty")
    op = Operator(world, "ST01")
    op.send("start_job", dict(START_PAYLOAD, target_t=1))
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if damage == "checksum":
        envelope["sha256"] = "0" * 64
    elif damage == "configuration":
        envelope["payload"]["configuration"]["material"]["coal"]["density_t_per_m3"] = .9
    elif damage == "ledger":
        envelope["payload"]["material"]["ledger"]["initial_m3"] = 10
    else:
        envelope["payload"]["jobs"][0]["completed_t"] = 2
    if damage != "checksum":
        body = {key: envelope[key] for key in ("format", "saved_at_utc", "payload")}
        # Recompute checksum to prove semantic/config validation is independent.
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        envelope["sha256"] = hashlib.sha256(encoded).hexdigest()
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    path.with_name(path.name + ".bak").unlink()
    restarted = World(snapshot_path=path)
    assert restarted.state()["persistence"]["recovery_required"]
    assert restarted.state()["material"]["scene"] == "uninitialized"
    assert restarted.state()["jobs"] == {}
    assert list(tmp_path.glob("material.json.rejected-*"))


def test_abrupt_process_exit_recovers_periodic_snapshot_and_ignores_partial_temp(tmp_path):
    path = tmp_path / "material.json"
    script = tmp_path / "crash.py"
    script.write_text(
        "import os, sys\nfrom yard_motion.world import World\n"
        "w=World(clock=lambda:0.0, snapshot_path=sys.argv[1])\n"
        "w.init_material('preset')\nw.advance(1)\nw.advance(.4)\n"
        "print(w.state()['sim_time'],flush=True)\nos._exit(7)\n", encoding="utf-8")
    # A partial temporary file left by an interrupted writer is never a source.
    (tmp_path / "material.json.interrupted.tmp").write_text("{partial", encoding="utf-8")
    completed = subprocess.run([sys.executable, "-c", script.read_text(encoding="utf-8"), str(path)],
                               cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 7
    assert float(completed.stdout.strip()) == pytest.approx(1.4)
    restarted = World(snapshot_path=path)
    assert restarted.state()["sim_time"] == pytest.approx(1)
    assert restarted.state()["material"]["inventory"]["total_m3"] > 0
    assert restarted.state()["persistence"]["loaded_from"] == "primary"


def test_failed_atomic_replacement_keeps_previous_valid_snapshot_and_save_time(tmp_path):
    path = tmp_path / "material.json"
    world = World(snapshot_path=path)
    world.init_material("preset")
    previous_bytes = path.read_bytes()
    previous_save = world.state()["persistence"]["last_saved_at_utc"]
    # Force an actual filesystem replace failure after the temporary file write.
    path.rename(tmp_path / "previous-valid.json")
    path.mkdir()
    world.advance(1)
    status = world.state()["persistence"]
    assert "SNAPSHOT_SAVE_FAILED" in status["error"]
    assert status["last_saved_at_utc"] == previous_save
    assert path.with_name(path.name + ".bak").read_bytes() == previous_bytes
    assert not list(tmp_path.glob("*.tmp"))


def test_authenticated_reset_of_restored_stopped_job_replaces_coal_and_is_saved(tmp_path):
    path = tmp_path / "material.json"
    world = World(clock=lambda: 0.0, snapshot_path=path)
    world.init_material("preset")
    op = Operator(world, "RC01", "reset-client")
    op.send("start_job", dict(START_PAYLOAD, target_t=10))
    restarted = World(clock=lambda: 0.0, snapshot_path=path)
    before_version = restarted.state()["material"]["version"]
    st = Operator(restarted, "ST01", "reset-client")
    rc = Operator(restarted, "RC01", "reset-client")
    controls = [dict(machine_id="RC01", token=rc.creds[1], generation=rc.creds[2])]
    st.send("reset_material", dict(mode="empty", confirm=True, controls=controls))
    backup = json.loads(path.with_name(path.name + ".bak").read_text(encoding="utf-8"))
    assert backup["payload"]["material"]["scene"] == "preset"
    again = World(snapshot_path=path)
    material = again.state()["material"]
    assert material["version"] > before_version
    assert material["inventory"]["total_m3"] == 0
    assert material["ledger"] == dict(initial_m3=0.0, received_m3=0.0, output_m3=0.0)
    assert next(iter(again.state()["jobs"].values()))["saved_status"] == "terminated"
    new = Operator(again, "RC01")
    with pytest.raises(MotionError):
        new.send("resume_job")
