"""Manual material jobs: lifecycle and stacking flow limiting.

A stacking job pours coal at the boom-front discharge point derived from the
authoritative machine pose. The actual flow is the minimum of the requested
flow, the belt capability curve (configurable, monotonic, zero at zero speed)
and what the falling-core kernel can geometrically accept; refused volume is
never counted as input. Wheel or belt motion without a job transfers nothing.
"""
import uuid
from collections import OrderedDict

from .errors import MotionError, finite
from .geometry import POSE_AXES

JOB_HISTORY_LIMIT = 512


def belt_capability_t_per_h(machine, coal):
    """Linear demo capability curve: full capability at max belt speed, zero at rest."""
    belt = machine.belt
    top = belt.config["max_speed"]
    if top <= 0 or belt.speed <= 0:
        return 0.0
    return coal["flow_capability_t_per_h"] * min(belt.speed, top) / top


def _contains(rect, x, z):
    return rect["x"][0] <= x <= rect["x"][1] and rect["z"][0] <= z <= rect["z"][1]


class MaterialJobs:
    def __init__(self, material, geometry):
        self.material = material
        self.geometry = geometry
        self.records = OrderedDict()
        self.active = {}  # machine_id -> job_id while running or paused

    def snapshot(self):
        return {job_id: dict(job) for job_id, job in self.records.items()}

    def any_active(self):
        return bool(self.active)

    def _job_of(self, machine):
        job_id = self.active.get(machine.config["machine_id"])
        if job_id is None:
            raise MotionError("JOB_NONE", "该设备没有进行中的物料作业", 409)
        return self.records[job_id]

    def start_job(self, machine, zone, mode, requested_flow_t_per_h, sim_time):
        if machine.config["role"] != "Stacking":
            raise MotionError("JOB_UNSUPPORTED", "该设备的物料作业暂未实现", 422)
        material = self.material
        if material.scene == "uninitialized":
            raise MotionError("MATERIAL_UNINITIALIZED", "物料场景尚未初始化", 409)
        machine_id = machine.config["machine_id"]
        if machine_id in self.active:
            raise MotionError("JOB_ACTIVE", "该设备已有进行中的物料作业", 409)
        job_zones = material.config["job_zones"]
        if not isinstance(zone, str) or zone not in job_zones:
            raise MotionError("INVALID_COMMAND", "未知作业区域", 422)
        if mode != "manual":
            raise MotionError("INVALID_COMMAND", "仅支持手动物料作业", 422)
        flow = finite(requested_flow_t_per_h)
        if flow <= 0:
            raise MotionError("INVALID_COMMAND", "请求流量必须为正数", 422)
        job_id = "job-" + uuid.uuid4().hex
        job = dict(job_id=job_id, machine_id=machine_id, zone=zone, mode="manual",
                   role="stacking", target_t=None, completed_t=0.0,
                   requested_flow_t_per_h=flow, actual_flow_t_per_h=0.0,
                   status="running", reason=None, plan_version="manual",
                   started_sim_time=sim_time)
        self.records[job_id] = job
        self.active[machine_id] = job_id
        while len(self.records) > JOB_HISTORY_LIMIT:
            oldest = next(iter(self.records))
            if oldest in self.active:
                break
            self.records.popitem(last=False)
        return job

    def pause_job(self, machine):
        job = self._job_of(machine)
        if job["status"] != "running":
            raise MotionError("JOB_STATE", "作业不在运行状态", 409)
        job["status"] = "paused"
        job["actual_flow_t_per_h"] = 0.0
        job["reason"] = None

    def resume_job(self, machine):
        job = self._job_of(machine)
        if job["status"] != "paused":
            raise MotionError("JOB_STATE", "作业不在暂停状态", 409)
        job["status"] = "running"

    def terminate_job(self, machine):
        job = self._job_of(machine)
        if job["status"] not in ("running", "paused"):
            raise MotionError("JOB_STATE", "作业已结束", 409)
        job["status"] = "terminated"
        job["actual_flow_t_per_h"] = 0.0
        job["reason"] = None
        self.active.pop(machine.config["machine_id"], None)

    def step(self, machines, dt):
        """Advance every running job by dt: derive the outlet from the authoritative
        pose, clamp the flow to request/capability/geometric acceptance, and deposit."""
        if dt <= 0:
            return  # zero-length steps transfer nothing (advance(0) is legal)
        coal = self.material.config["coal"]
        domain = self.material.config["domain"]
        for job in self.records.values():
            if job["status"] != "running":
                continue
            machine = machines[job["machine_id"]]
            scene = machine.config["scene"]
            pose = {axis: machine.axes[axis].position for axis in POSE_AXES}
            outlet = self.geometry.discharge_point(scene, **pose)
            x, z = outlet["x"], outlet["z"]
            if not _contains(domain, x, z):
                job["actual_flow_t_per_h"] = 0.0
                job["reason"] = "OUT_OF_DOMAIN"
                continue
            if not _contains(self.material.config["job_zones"][job["zone"]], x, z):
                job["actual_flow_t_per_h"] = 0.0
                job["reason"] = "OUT_OF_ZONE"
                continue
            capability = belt_capability_t_per_h(machine, coal)
            attempted = min(job["requested_flow_t_per_h"], capability)
            if attempted <= 0:
                job["actual_flow_t_per_h"] = 0.0
                job["reason"] = "BELT_NOT_RUNNING"
                continue
            density = coal["density_t_per_m3"]
            volume = attempted / 3600.0 * dt / density
            result = self.material.deposit(x, z, volume)
            accepted = result["accepted_m3"]
            job["completed_t"] += accepted * density
            job["actual_flow_t_per_h"] = accepted * density / dt * 3600.0
            if accepted < volume - 1e-12:
                job["reason"] = "RECEIVE_LIMITED"
            elif attempted < job["requested_flow_t_per_h"] - 1e-12:
                job["reason"] = "CAPABILITY_LIMITED"
            else:
                job["reason"] = None
