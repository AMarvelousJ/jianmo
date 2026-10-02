"""Manual material jobs: lifecycle and stacking flow limiting.

A stacking job pours coal at the boom-front discharge point derived from the
authoritative machine pose. The actual flow is the minimum of the requested
flow, the belt capability curve (configurable, monotonic, zero at zero speed)
and what the falling-core kernel can geometrically accept; refused volume is
never counted as input. Wheel or belt motion without a job transfers nothing.
"""
import uuid
import copy
import math
from collections import OrderedDict

from .errors import MotionError, finite
from .geometry import POSE_AXES
from .cutting import swept_contacts

JOB_HISTORY_LIMIT = 512
TARGET_TOLERANCE_T = 1e-9
MATERIAL_MACHINE_IDS = ("ST01", "RC01")


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
        self.zone_owners = {}  # zone -> job_id; mutated under the World lock

    def zone_snapshot(self):
        return {zone: None if zone not in self.zone_owners else
                dict(job_id=self.zone_owners[zone],
                     machine_id=self.records[self.zone_owners[zone]]["machine_id"])
                for zone in self.material.config["job_zones"]}

    def _claim_zone(self, job):
        owner_id = self.zone_owners.get(job["zone"])
        if owner_id is not None and owner_id != job["job_id"]:
            owner = self.records[owner_id]["machine_id"]
            raise MotionError("ZONE_BUSY", f"作业区 {job['zone']} 已由 {owner} 占用", 409)
        self.zone_owners[job["zone"]] = job["job_id"]

    def _free_zone(self, job):
        if self.zone_owners.get(job["zone"]) == job["job_id"]:
            self.zone_owners.pop(job["zone"])

    def release_zone(self, machine):
        job_id = self.active.get(machine.config["machine_id"])
        if job_id is not None:
            self._free_zone(self.records[job_id])

    def snapshot(self):
        return {job_id: dict(copy.deepcopy(job), remaining_t=None if job["target_t"] is None else
                            max(0.0, job["target_t"] - job["completed_t"]))
                for job_id, job in self.records.items()}

    def any_active(self):
        return bool(self.active)

    def any_unstopped(self):
        return any(self.records[job_id]["status"] != "stopped" for job_id in self.active.values())

    def validate_archive(self, records, sim_time):
        if not isinstance(records, list) or len(records) > JOB_HISTORY_LIMIT:
            raise ValueError("SNAPSHOT_JOB_HISTORY")
        ids, active_machines = set(), set()
        states = {"running", "paused", "stopped", "completed", "terminated", "incomplete"}
        for job in records:
            if not isinstance(job, dict) or not isinstance(job["job_id"], str) or job["job_id"] in ids:
                raise ValueError("SNAPSHOT_JOB_ID")
            ids.add(job["job_id"])
            if job["machine_id"] not in MATERIAL_MACHINE_IDS or job["zone"] not in self.material.config["job_zones"]:
                raise ValueError("SNAPSHOT_JOB_MACHINE_ZONE")
            if job["mode"] != "manual" or job["plan_version"] != "manual" or job["status"] not in states:
                raise ValueError("SNAPSHOT_JOB_STATE")
            if job["role"] != ("stacking" if job["machine_id"].startswith("ST") else "reclaiming"):
                raise ValueError("SNAPSHOT_JOB_ROLE")
            for key in ("completed_t", "requested_flow_t_per_h", "actual_flow_t_per_h", "started_sim_time"):
                if type(job[key]) not in (float, int) or not math.isfinite(job[key]) or job[key] < 0:
                    raise ValueError("SNAPSHOT_JOB_NUMBER")
            if job["requested_flow_t_per_h"] <= 0 or job["started_sim_time"] > sim_time:
                raise ValueError("SNAPSHOT_JOB_PROGRESS")
            target = job["target_t"]
            if target is not None and (type(target) not in (float, int) or not math.isfinite(target) or target <= 0 or job["completed_t"] > target + TARGET_TOLERANCE_T):
                raise ValueError("SNAPSHOT_JOB_TARGET")
            original = job.get("saved_status", job["status"]) if job["status"] == "stopped" else job["status"]
            if original not in states:
                raise ValueError("SNAPSHOT_JOB_SAVED_STATE")
            if original == "completed" and (target is None or abs(target - job["completed_t"]) > TARGET_TOLERANCE_T):
                raise ValueError("SNAPSHOT_JOB_COMPLETION")
            if original in ("running", "paused", "stopped"):
                if job["machine_id"] in active_machines:
                    raise ValueError("SNAPSHOT_DUPLICATE_ACTIVE_JOB")
                active_machines.add(job["machine_id"])

    def restore_archive(self, records):
        self.records.clear()
        self.active.clear()
        self.zone_owners.clear()
        for saved in records:
            job = copy.deepcopy(saved)
            original = job.get("saved_status", job["status"]) if job["status"] == "stopped" else job["status"]
            job.update(status="stopped", saved_status=original, actual_flow_t_per_h=0.0, reason="SERVER_RESTART")
            self.records[job["job_id"]] = job
            if original in ("running", "paused", "stopped"):
                self.active[job["machine_id"]] = job["job_id"]

    def _job_of(self, machine):
        job_id = self.active.get(machine.config["machine_id"])
        if job_id is None:
            raise MotionError("JOB_NONE", "该设备没有进行中的物料作业", 409)
        return self.records[job_id]

    def start_job(self, machine, zone, mode, requested_flow_t_per_h, sim_time, target_t=None):
        if machine.config["machine_id"] not in MATERIAL_MACHINE_IDS:
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
        if target_t is not None:
            target_t = finite(target_t)
            if target_t <= 0:
                raise MotionError("INVALID_COMMAND", "目标吨位必须为正数", 422)
        job_id = "job-" + uuid.uuid4().hex
        job = dict(job_id=job_id, machine_id=machine_id, zone=zone, mode="manual",
                   role="stacking" if machine.config["role"] == "Stacking" else "reclaiming", target_t=target_t, completed_t=0.0,
                   requested_flow_t_per_h=flow, actual_flow_t_per_h=0.0,
                   status="running", reason=None, plan_version="manual",
                   started_sim_time=sim_time)
        self._claim_zone(job)
        self.records[job_id] = job
        self.active[machine_id] = job_id
        while len(self.records) > JOB_HISTORY_LIMIT:
            active_ids = set(self.active.values())
            oldest_finished = next((key for key in self.records if key not in active_ids), None)
            if oldest_finished is None:
                break
            del self.records[oldest_finished]
        return job

    def pause_job(self, machine):
        job = self._job_of(machine)
        if job["status"] != "running":
            raise MotionError("JOB_STATE", "作业不在运行状态", 409)
        job["status"] = "paused"
        job["actual_flow_t_per_h"] = 0.0
        job["reason"] = None

    def protect(self, machine, reason, terminate=False):
        job_id=self.active.get(machine.config["machine_id"])
        if job_id is None: return
        job=self.records[job_id]
        job.update(status="terminated" if terminate else "paused",actual_flow_t_per_h=0.0,reason=reason)
        if terminate:
            self._free_zone(job)
            self.active.pop(machine.config["machine_id"],None)

    def resume_job(self, machine):
        job = self._job_of(machine)
        if job["status"] not in ("paused", "stopped"):
            raise MotionError("JOB_STATE", "作业不在暂停状态", 409)
        self._claim_zone(job)
        job["status"] = "running"
        job["reason"] = None

    def terminate_job(self, machine):
        job = self._job_of(machine)
        if job["status"] not in ("running", "paused", "stopped"):
            raise MotionError("JOB_STATE", "作业已结束", 409)
        job["status"] = "terminated"
        job["actual_flow_t_per_h"] = 0.0
        job["reason"] = None
        self._free_zone(job)
        self.active.pop(machine.config["machine_id"], None)

    def finish_job(self, machine):
        """Explicit manual finish; report contacts without changing any coal.

        A whole wheel revolution checks only this pose. Uncontacted stock can
        still be reachable after moving the machine, so global reachability is
        unknown until a workspace search is implemented.
        """
        job = self._job_of(machine)
        if job["target_t"] is None:
            raise MotionError("JOB_TARGET_REQUIRED", "无目标作业请使用终止命令", 409)
        inventory = self.material.state()["inventory"]
        report = dict(scope="inventory_only", material_version=self.material.version,
                      residual_m3=inventory["total_m3"], residual_t=inventory["total_t"],
                      contactable_m3=None, uncontacted_m3=None,
                      whole_workspace_unreachable_m3=None)
        if job["role"] == "reclaiming":
            pose = {axis: machine.axes[axis].position for axis in POSE_AXES}
            contacts = swept_contacts(self.material, self.geometry, machine.config["scene"],
                                      pose, pose, machine.wheel.distance, machine.wheel.distance + 360)
            contactable = min(inventory["total_m3"], sum(contacts.values()))
            report.update(scope="current_pose_full_revolution", contactable_m3=contactable,
                          uncontacted_m3=max(0.0, inventory["total_m3"] - contactable))
        job.update(status="incomplete", reason="OPERATOR_FINISHED", actual_flow_t_per_h=0.0,
                   finish_report=report)
        self._free_zone(job)
        self.active.pop(machine.config["machine_id"], None)

    def step(self, machines, dt, previous=None):
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
            if job["role"] == "reclaiming":
                belt_cap=belt_capability_t_per_h(machine,coal)
                wheel_cap=coal["flow_capability_t_per_h"]*max(0,machine.wheel.speed)/machine.wheel.config["max_speed"]
                requested=min(job["requested_flow_t_per_h"],belt_cap,wheel_cap)
                if requested<=0:
                    job["actual_flow_t_per_h"]=0.0
                    job["reason"]="WHEEL_NOT_RUNNING" if wheel_cap<=0 else "BELT_NOT_RUNNING"
                    continue
                prev=previous[job["machine_id"]]
                contacts=swept_contacts(self.material,self.geometry,scene,prev["pose"],pose,
                                        prev["phase"],machine.wheel.distance)
                density=coal["density_t_per_m3"]
                actual=self.material.remove_contacts(contacts,self._requested_volume(job, requested, dt, density))
                job["completed_t"]+=actual*density
                job["actual_flow_t_per_h"]=actual*density/dt*3600
                job["reason"]="NO_CONTACT" if actual<=0 else (
                    "CONTACT_LIMITED" if job["actual_flow_t_per_h"]<requested-1e-8 else (
                    "CAPABILITY_LIMITED" if requested<job["requested_flow_t_per_h"] else None))
                self._complete_if_target_reached(job)
                continue
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
            volume = self._requested_volume(job, attempted, dt, density)
            result = self.material.deposit(x, z, volume,ceiling_y=outlet["y"])
            accepted = result["accepted_m3"]
            job["completed_t"] += accepted * density
            job["actual_flow_t_per_h"] = accepted * density / dt * 3600.0
            if accepted < volume - 1e-12:
                job["reason"] = "RECEIVE_LIMITED"
            elif attempted < job["requested_flow_t_per_h"] - 1e-12:
                job["reason"] = "CAPABILITY_LIMITED"
            else:
                job["reason"] = None
            self._complete_if_target_reached(job)

    @staticmethod
    def _requested_volume(job, flow, dt, density):
        tonnes = flow / 3600.0 * dt
        if job["target_t"] is not None:
            tonnes = min(tonnes, max(0.0, job["target_t"] - job["completed_t"]))
        return tonnes / density

    def _complete_if_target_reached(self, job):
        if job["target_t"] is not None and job["target_t"] - job["completed_t"] <= TARGET_TOLERANCE_T:
            job.update(status="completed", actual_flow_t_per_h=0.0, reason=None)
            self._free_zone(job)
            self.active.pop(job["machine_id"], None)
