import copy
import json
import math
import secrets
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

from .errors import MotionError, finite
from .geometry import POSE_AXES, GeometryCalibration
from .jobs import MaterialJobs
from .material import MaterialDomain
from .motion import Axis, Drive


class Machine:
    def __init__(self, config):
        self.config = config
        self.axes = {name: Axis(c) for name, c in config["axes"].items()}
        self.wheel = Drive(config["wheel"], 6)
        self.belt = Drive(config["belt"], 1)
        self.lease = None
        self.estop = False
        self.last_seq = 0
        self.results = OrderedDict()
        self.reason = None
        self.last_command_id = None

    def moving(self):
        return any(a.velocity or a.mode in ("target", "jog") for a in self.axes.values()) or any(
            d.speed or d.target_speed for d in (self.wheel, self.belt))

    def stop(self, immediate=False):
        for axis in self.axes.values():
            axis.stop(immediate)
        self.wheel.stop(immediate)
        self.belt.stop(immediate)


class World:
    def __init__(self, config=None, clock=time.monotonic, material_config=None):
        self.config = config or json.loads((Path(__file__).resolve().parents[1] / "config/machines.json").read_text(encoding="utf-8"))
        self._validate_config()
        self.clock = clock
        self.lock = threading.RLock()
        self.machines = {c["machine_id"]: Machine(c) for c in self.config["machines"]}
        self.material = MaterialDomain(material_config)
        self.geometry = GeometryCalibration()
        self.geometry.validate_against_machines(self.config["machines"])
        self.jobs = MaterialJobs(self.material, self.geometry)
        self.instance = str(uuid.uuid4())
        self.sim_time = 0.0
        self.seq = 0
        self.generation = 0

    def _validate_config(self):
        ids = set()
        for m in self.config["machines"]:
            if m["machine_id"] in ids:
                raise ValueError("Duplicate machine ID")
            ids.add(m["machine_id"])
            for c in m["axes"].values():
                if not all(math.isfinite(v) for v in c.values()) or not c["minimum"] <= c["initial"] <= c["maximum"]:
                    raise ValueError("Invalid axis configuration")
                if c["minimum"] >= c["maximum"] or any(c[k] <= 0 for k in ("max_speed", "acceleration", "deceleration", "tolerance")):
                    raise ValueError("Invalid motion limits")
            for c in (m["wheel"], m["belt"]):
                if any(not math.isfinite(v) or v <= 0 for v in c.values()):
                    raise ValueError("Invalid drive configuration")
        if len(ids) != 21:
            raise ValueError("Expected 21 machines")

    def machine(self, machine_id):
        if machine_id not in self.machines:
            raise MotionError("UNKNOWN_MACHINE", "未知设备", 404)
        return self.machines[machine_id]

    def _expire(self, m):
        if m.lease and m.lease["state"] == "owned" and self.clock() >= m.lease["expires"]:
            self._release(m, "CONNECTION_TIMEOUT")
        if m.lease and m.lease["state"] == "releasing" and not m.moving():
            m.lease = None

    def _release(self, m, reason):
        self.jobs.protect(m,reason)
        m.stop()
        m.lease["state"] = "releasing"
        m.reason = reason

    def _owned(self, m, client_id, token, generation):
        self._expire(m)
        lease = m.lease
        if not lease or lease["client_id"] != client_id or lease["token"] != token or lease["generation"] != generation:
            raise MotionError("CONTROL_REQUIRED", "需要有效控制权", 403)
        if lease["state"] != "owned":
            raise MotionError("CONTROL_RELEASING", "设备正在停稳释放控制权")

    def acquire(self, machine_id, client_id):
        with self.lock:
            if not client_id or len(client_id) > 128:
                raise MotionError("INVALID_COMMAND", "客户端标识无效", 422)
            m = self.machine(machine_id)
            self._expire(m)
            if m.lease:
                raise MotionError("CONTROL_RELEASING" if m.lease["state"] == "releasing" else "CONTROL_HELD", "控制权已占用")
            self.generation += 1
            m.lease = dict(client_id=client_id, token=secrets.token_urlsafe(24), generation=self.generation,
                           expires=self.clock() + self.config["lease_timeout"], state="owned")
            m.last_seq = 0
            m.results.clear()
            self.seq += 1
            return dict(copy.deepcopy(m.lease), snapshot_seq=self.seq)

    def heartbeat(self, machine_id, client_id, token, generation):
        with self.lock:
            m = self.machine(machine_id)
            self._owned(m, client_id, token, generation)
            m.lease["expires"] = self.clock() + self.config["lease_timeout"]
            return dict(ok=True)

    def release(self, machine_id, client_id, token, generation):
        with self.lock:
            m = self.machine(machine_id)
            self._owned(m, client_id, token, generation)
            self._release(m, "CONTROL_RELEASED")
            self.seq += 1
            return dict(ok=True)

    def command(self, machine_id, client_id, token, generation, command_id, command_seq, kind, payload):
        with self.lock:
            m = self.machine(machine_id)
            self._owned(m, client_id, token, generation)
            try:
                fingerprint = json.dumps([command_seq, kind, payload], sort_keys=True, allow_nan=False)
            except (ValueError, TypeError):
                raise MotionError("INVALID_COMMAND", "命令参数不可序列化或包含非有限值", 422)
            if command_id in m.results:
                prior, result = m.results[command_id]
                if prior != fingerprint:
                    raise MotionError("INVALID_COMMAND", "同一命令编号的内容不一致", 422)
                return copy.deepcopy(result)
            if not command_id or not isinstance(command_seq, int) or isinstance(command_seq, bool) or command_seq <= m.last_seq:
                raise MotionError("STALE_COMMAND", "命令序号已过期")
            if m.estop and kind not in ("clear_estop", "reset", "estop", "stop", "stop_jog", "pause_job", "terminate_job", "finish_job"):
                raise MotionError("ESTOP_LATCHED", "急停已锁定，请先解除")
            self._apply(m, kind, payload)
            m.last_seq = command_seq
            m.last_command_id = command_id
            self.seq += 1
            result = dict(command_id=command_id, accepted=True, snapshot_seq=self.seq, machine=self._snapshot(m))
            m.results[command_id] = (fingerprint, copy.deepcopy(result))
            if len(m.results) > 512:
                m.results.popitem(last=False)
            return result

    def _apply(self, m, kind, p):
        allowed = {
            "set_targets": {"targets"}, "jog": {"axis", "direction", "speed"}, "stop_jog": {"axis"},
            "set_wheel": {"speed"}, "set_belt": {"speed"}, "stop": set(), "estop": set(),
            "clear_estop": set(), "reset": set(),
            "start_job": {"zone", "mode", "requested_flow_t_per_h", "target_t"},
            "pause_job": set(), "resume_job": set(), "terminate_job": set(), "finish_job": set(),
        }
        if kind not in allowed or not isinstance(p, dict) or set(p) - allowed[kind]:
            raise MotionError("INVALID_COMMAND", "命令类型或字段无效", 422)
        if kind == "set_targets":
            targets = p.get("targets")
            if not isinstance(targets, dict) or not targets or set(targets) - set(m.axes):
                raise MotionError("INVALID_COMMAND", "目标轴无效", 422)
            values = {}
            for name, value in targets.items():
                value = finite(value)
                c = m.axes[name].config
                if not c["minimum"] <= value <= c["maximum"]:
                    raise MotionError("OUT_OF_RANGE", "目标超出行程", 422)
                values[name] = value
            for name, value in values.items():
                m.axes[name].set_target(value)
        elif kind == "jog":
            name = p.get("axis")
            direction = p.get("direction")
            if not isinstance(name, str) or name not in m.axes or isinstance(direction, bool) or direction not in (-1, 1):
                raise MotionError("INVALID_COMMAND", "轴或方向无效", 422)
            a = m.axes[name]
            speed = finite(p.get("speed"))
            if not 0 < speed <= a.config["max_speed"]:
                raise MotionError("OUT_OF_RANGE", "速度超出范围", 422)
            if (direction > 0 and a.position >= a.config["maximum"]) or (direction < 0 and a.position <= a.config["minimum"]):
                raise MotionError("OUT_OF_RANGE", "已到行程限位", 422)
            a.jog(direction * speed, self.clock() + self.config["jog_timeout"])
        elif kind == "stop_jog":
            name = p.get("axis")
            if name is not None and (not isinstance(name, str) or name not in m.axes):
                raise MotionError("INVALID_COMMAND", "轴无效", 422)
            for n, a in m.axes.items():
                if (name is None or n == name) and a.mode == "jog":
                    a.stop()
        elif kind in ("set_wheel", "set_belt"):
            drive = m.wheel if kind == "set_wheel" else m.belt
            speed = finite(p.get("speed"))
            if not 0 <= speed <= drive.config["max_speed"]:
                raise MotionError("OUT_OF_RANGE", "速度超出范围", 422)
            drive.target_speed = speed
            if speed==0: self.jobs.protect(m,kind)
        elif kind == "stop":
            self.jobs.protect(m,kind)
            m.stop()
        elif kind == "estop":
            self.jobs.protect(m,kind)
            m.stop(True)
            m.estop = True
        elif kind == "clear_estop":
            m.estop = False
        elif kind == "reset":
            self.jobs.protect(m,kind,terminate=True)
            for a in m.axes.values():
                a.reset()
            m.wheel.reset()
            m.belt.reset()
        elif kind == "start_job":
            self.jobs.start_job(m, p.get("zone"), p.get("mode"), p.get("requested_flow_t_per_h"), self.sim_time,
                                target_t=p.get("target_t"))
        elif kind == "pause_job":
            self.jobs.pause_job(m)
        elif kind == "resume_job":
            self.jobs.resume_job(m)
        elif kind == "terminate_job":
            self.jobs.terminate_job(m)
        elif kind == "finish_job":
            self.jobs.finish_job(m)
        m.reason = kind

    def init_material(self, mode, confirm=False):
        with self.lock:
            if self.jobs.any_active():
                raise MotionError("JOB_ACTIVE", "物料作业进行中，不能重新初始化场景", 409)
            current = self.material.state()
            if current["scene"] != "uninitialized" and current["inventory"]["total_m3"] > 0 and not confirm:
                raise MotionError("CONFIRM_REQUIRED", "物料场景非空，重新初始化需要二次确认", 409)
            self.material.init_scene(mode)
            self.seq += 1
            return self.material.state()

    def machine_geometry(self, machine_id):
        with self.lock:
            m = self.machine(machine_id)
            scene = m.config["scene"]
            pose = {axis: m.axes[axis].position for axis in POSE_AXES}
            return dict(machine_id=machine_id,
                        geometry_version=self.geometry.config["version"],
                        pose=dict(pose),
                        discharge_point=self.geometry.discharge_point(scene, **pose),
                        wheel_envelope=self.geometry.wheel_envelope(scene, **pose))

    def material_grid(self):
        """Read shape, classification and inventory at one locked material version.

        Flat arrays use index = z_index * cells_x + x_index. Coordinates are
        cell centres: origin + (index + 0.5) * cell_size, in backend metres.
        Full grids are fetched on demand, separate from motion polling.
        """
        with self.lock:
            material = self.material
            return dict(server_instance_id=self.instance, snapshot_seq=self.seq,
                        sim_time=self.sim_time, material_config_version=material.config["version"],
                        material=material.state(),
                        grid=dict(material.config["grid"],
                                  array_order="z-major", sample_location="cell_center",
                                  coal_thickness_m=list(material.heights),
                                  ground_elevation_m=list(material.ground),
                                  zone_codes=list(material.zone_code),
                                  zone_labels={"0": "outside", "1": "spill", "2": "yard"}))

    def advance(self, dt):
        with self.lock:
            dt = finite(dt)
            if dt < 0 or dt > 1:
                raise ValueError("Step must be between 0 and 1 second")
            previous={name:dict(pose={a:m.axes[a].position for a in POSE_AXES},phase=m.wheel.distance)
                      for name,m in self.machines.items()}
            for m in self.machines.values():
                self._expire(m)
                for a in m.axes.values():
                    if a.mode == "jog" and self.clock() >= a.jog_deadline:
                        a.stop()
                        m.reason = "JOG_TIMEOUT"
                    a.update(dt)
                m.wheel.update(dt)
                m.belt.update(dt)
                self._expire(m)
            self.jobs.step(self.machines, dt, previous)
            self.material.settle_slopes()
            self.sim_time += dt
            self.seq += 1

    def _snapshot(self, m):
        lease = m.lease
        return dict(machine_id=m.config["machine_id"], role=m.config["role"],
                    axes={n: a.state() for n, a in m.axes.items()}, wheel=m.wheel.state(), belt=m.belt.state(),
                    estop_latched=m.estop, running=bool(m.moving()), last_command_id=m.last_command_id,
                    reason=m.reason, control=None if not lease else dict(owner_id=lease["client_id"],
                    generation=lease["generation"], state=lease["state"], remaining=max(0, lease["expires"] - self.clock())))

    def state(self):
        with self.lock:
            for m in self.machines.values():
                self._expire(m)
            return dict(server_instance_id=self.instance, config_version=self.config["version"],
                        sim_time=self.sim_time, snapshot_seq=self.seq,
                        material=self.material.state(),
                        jobs=self.jobs.snapshot(),
                        machines={n: self._snapshot(m) for n, m in self.machines.items()})
