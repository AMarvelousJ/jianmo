"""One top-layer strip, planned from the current preview material and actual rig.

This controller schedules motion only. ReclaimPilot owns cutting, inventory and
the final collision guard. Completion means one strip, never the entire pile.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import logging
import time
import uuid

import numpy as np

from .errors import MotionError

PLANNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rc01-planner')


def pose_of(machine):
    return {name: axis.position for name, axis in machine.axes.items()}


class AutoReclaim:
    VERSION = 'rc01-auto-single-strip-v1'
    SPEEDS = {'travel': .5, 'slew': 1., 'luff': 1.}
    CUTTING_SLEW_SPEED = .35
    ACTIVE = {'PLANNING', 'RAISING', 'POSITIONING', 'ALIGNING', 'DRIVES_READY', 'APPROACHING',
              'SWEEPING', 'EDGE_CONFIRM', 'STOPPING'}

    def __init__(self, pilot):
        self.pilot = pilot
        self.plan = None
        self.status = 'IDLE'
        self.reason = 'PLAN_REQUIRED'
        self.job_id = None
        self.base_m3 = 0.
        self.elapsed = self.no_progress = self.edge_time = 0.
        self.future = None
        self.planning_started = 0.
        self.taken = 0.
        self.exit_classification = None
        self.edge_confirmed = False
        self.exit_elapsed = 0.

    @property
    def active(self):
        return self.status in self.ACTIVE

    def command(self, machine, kind, payload):
        if self.active or machine.moving():
            raise MotionError('MACHINE_MOVING', '请先停止自动任务并停稳 RC01', 409)
        if kind == 'plan_auto_reclaim':
            if payload or not self.pilot.initialized:
                raise MotionError('INVALID_COMMAND', '请先创建测试煤堆，计划参数应为空', 422)
            worker = AutoReclaim(copy.deepcopy(self.pilot))
            self.future = PLANNER.submit(worker._plan, copy.deepcopy(machine))
            self.planning_started = time.monotonic()
            self.plan = None
            self.job_id = None
            self.taken = 0.
            self.exit_classification = None
            self.edge_confirmed = False
            self.edge_time = self.elapsed = 0.
            self.pilot.enabled = False
            self.status, self.reason = 'PLANNING', 'READ_ONLY_GEOMETRY_SEARCH'
            return
        if set(payload) != {'plan_id'} or not self.plan or payload['plan_id'] != self.plan['plan_id']:
            raise MotionError('PLAN_REQUIRED', '请先生成有效计划', 409)
        if self.status != 'PLANNED':
            raise MotionError('STALE_PLAN', '任务已停止，请重新生成计划', 409)
        if self.plan['material_version'] != self.pilot.version or self.plan['geometry_version'] != self.pilot.geometry['version']:
            raise MotionError('STALE_PLAN', '煤形或标定已变化，请重新生成计划', 409)
        if pose_of(machine) != self.plan['start_pose']:
            raise MotionError('STALE_PLAN', '设备姿态已变化，请重新生成计划', 409)
        self.base_m3 = self.pilot.reclaimed_m3
        self.job_id = uuid.uuid4().hex
        self.elapsed = self.no_progress = self.edge_time = 0.
        self.taken = 0.
        self.exit_classification = None
        self.edge_confirmed = False
        self.exit_elapsed = 0.
        self.pilot.enabled = False
        self.pilot.cut_floor_y = self.plan['layer_bottom_y']
        self.status, self.reason = 'RAISING', 'SAFE_ENTRY'
        self._target(machine, 'luff', self.plan['safe_luff'])

    def _plan(self, machine):
        p = self.pilot
        floor = p.GROUND + float(p.heights.max()) - .5
        if floor <= p.GROUND:
            raise MotionError('NO_PLAN', '煤量不足以生成顶层单带计划', 409)
        travel_config = machine.axes['travel'].config
        travel = float(np.clip(np.average(p.x, weights=p.heights), travel_config['minimum'], travel_config['maximum']))
        safe = machine.axes['luff'].config['maximum']
        # Search safe poses with actual cutting contact above this layer floor.
        # 36 degrees spans one bucket pitch of this exported ten-bucket rig.
        for luff in np.arange(0., -4.01, -.5):
            if not machine.axes['luff'].config['minimum'] <= luff <= safe:
                continue
            run = []
            for slew in np.arange(-24., 24.01, 3.):
                pose = dict(travel=travel, slew=float(slew), luff=float(luff))
                usable = not p.collides(pose) and p.contact_depths(pose, 0, 36, .02, floor).sum() > 1e-8
                if usable:
                    run.append(float(slew))
                else:
                    if len(run) >= 3:
                        break
                    run = []
            if len(run) < 3:
                continue
            start = dict(travel=travel, slew=run[0], luff=float(luff))
            end = dict(start, slew=run[-1])
            if not p.path_clear(start, end):
                continue
            plan = dict(plan_id=uuid.uuid4().hex, scope='single_top_layer_strip',
                        pile_id='RC01_TEST', material_version=p.version,
                        geometry_version=p.geometry['version'], layer_bottom_y=floor,
                        travel=travel, luff=float(luff), slew_start=run[0], slew_end=run[-1],
                        safe_luff=safe, speed_limits=dict(self.SPEEDS, cutting_slew=self.CUTTING_SLEW_SPEED),
                        wheel_rpm=6., belt_m_s=2., remaining_m3=float(p.heights.sum()*p.CELL**2))
            plan['start_pose'] = pose_of(machine)
            plan['wheel_path'] = [p.frame(dict(start, slew=float(a)))[2].tolist()
                                  for a in np.linspace(run[0], run[-1], 25)]
            self._entry_path(machine, plan)
            return plan
        raise MotionError('NO_SAFE_STRIP', '未找到安全且有料的顶层回转带，请检查当前煤形与姿态', 409)

    def _entry_path(self, machine, plan):
        pose = pose_of(machine)
        for name, value in [('luff', plan['safe_luff']), ('travel', plan['travel']),
                            ('slew', plan['slew_start']), ('luff', plan['luff'])]:
            candidate = dict(pose, **{name: value})
            if not self.pilot.path_clear(pose, candidate):
                raise MotionError('NO_SAFE_ENTRY', '安全对垛路径受阻，请先手动退出', 409)
            pose = candidate

    def _target(self, machine, axis, value):
        speed = self.CUTTING_SLEW_SPEED if self.status == 'SWEEPING' and axis == 'slew' else self.SPEEDS[axis]
        machine.axes[axis].set_target(value, speed)

    def before_step(self, machine, dt):
        self.sync(machine)
        if not self.active:
            return
        if self.status == 'PLANNING':
            if time.monotonic()-self.planning_started > 30:
                self.stop(machine, 'FAILED', 'PLAN_TIMEOUT')
            return
        self.elapsed += dt
        if self.elapsed > 180:
            self.stop(machine, 'FAILED', 'ACTION_TIMEOUT')

    def after_step(self, machine, dt):
        self.sync(machine)
        if not self.active:
            return
        p = self.pilot
        if self.job_id:
            self.taken = max(0., p.reclaimed_m3-self.base_m3)
        if self.status not in ('PLANNING', 'SWEEPING', 'EDGE_CONFIRM', 'STOPPING'):
            self.no_progress = self.no_progress+dt if p.blocked else 0.
            if self.no_progress > 2:
                self.stop(machine, 'BLOCKED', 'ENTRY_PATH_BLOCKED')
                return
        if self.status == 'RAISING' and machine.axes['luff'].mode == 'idle':
            self.status = 'POSITIONING'
            self._target(machine, 'travel', self.plan['travel'])
        elif self.status == 'POSITIONING' and machine.axes['travel'].mode == 'idle':
            self.status = 'ALIGNING'
            self._target(machine, 'slew', self.plan['slew_start'])
        elif self.status == 'ALIGNING' and machine.axes['slew'].mode == 'idle':
            self.status = 'DRIVES_READY'
            machine.wheel.target_speed = self.plan['wheel_rpm']
            machine.belt.target_speed = self.plan['belt_m_s']
        elif self.status == 'DRIVES_READY' and machine.wheel.speed >= 5.99 and machine.belt.speed >= 1.99:
            self.status = 'APPROACHING'
            self._target(machine, 'luff', self.plan['luff'])
        elif self.status == 'APPROACHING' and machine.axes['luff'].mode == 'idle':
            self.status, self.reason = 'SWEEPING', 'SAFE_SHALLOW_CUT'
            p.enabled = True
            self._target(machine, 'slew', self.plan['slew_end'])
        elif self.status == 'SWEEPING':
            self.no_progress = self.no_progress+dt if p.blocked and p.actual_m3_s <= 1e-10 else 0.
            if self.no_progress > 5:
                self.stop(machine, 'BLOCKED', 'COAL_GUARD_NO_PROGRESS')
            elif machine.axes['slew'].mode == 'idle':
                self.status, self.reason = 'EDGE_CONFIRM', 'PLANNED_STRIP_EXIT'
                ahead = dict(pose_of(machine), slew=self.plan['slew_end']+3.)
                if p.collides(ahead):
                    self.exit_classification = 'GEOMETRY_LIMIT'
                elif p.contact_depths(ahead, 0, 36, .02, self.plan['layer_bottom_y']).sum() > 1e-8:
                    self.exit_classification = 'PLANNED_LIMIT'
                else:
                    self.exit_classification = 'MODEL_CLEAR'
        elif self.status == 'EDGE_CONFIRM':
            self.exit_elapsed += dt
            self.edge_time = self.edge_time+dt if p.actual_m3_s <= 1e-10 else 0.
            # The forefield must be clear AND the spinning wheel must show no
            # actual cutting for a full bucket pitch. Other exits are reported
            # as a limited strip ending, never as a detected material edge.
            pitch_seconds = 36/(machine.wheel.speed*6) if machine.wheel.speed > .001 else float('inf')
            if self.exit_classification != 'MODEL_CLEAR':
                self.stop(machine, 'STOPPING', 'SINGLE_STRIP_COMPLETE')
            elif self.edge_time >= pitch_seconds:
                self.edge_confirmed = True
                self.stop(machine, 'STOPPING', 'SINGLE_STRIP_COMPLETE')
            elif self.exit_elapsed > 20:
                self.stop(machine, 'BLOCKED', 'NO_STABLE_EDGE')
        elif self.status == 'STOPPING' and not machine.moving():
            self.status = 'COMPLETED'

    def stop(self, machine, status, reason):
        machine.stop()
        self.pilot.enabled = False
        self.pilot.actual_m3_s = 0.
        self.pilot.cut_floor_y = None
        self.status, self.reason = status, reason
        if self.future:
            self.future.cancel()
            self.future = None

    def sync(self, machine):
        if self.active and (not machine.lease or machine.lease['state'] != 'owned' or machine.estop):
            self.stop(machine, 'ESTOP' if machine.estop else 'CONTROL_LOST', 'ESTOP' if machine.estop else 'CONTROL_REQUIRED')
        if self.status == 'PLANNING' and self.future and self.future.done():
            try:
                self.plan = self.future.result()
                self.status, self.reason = 'PLANNED', 'EXPLICIT_START_REQUIRED'
            except Exception as error:
                logging.getLogger(__name__).exception('RC01 read-only planning failed')
                self.status, self.reason = 'FAILED', getattr(error, 'code', 'PLAN_FAILED')
            self.future = None

    def snapshot(self):
        return dict(version=self.VERSION, status=self.status, reason=self.reason,
                    plan=copy.deepcopy(self.plan), job_id=self.job_id,
                    job_reclaimed_m3=self.taken,
                    pile_remaining_m3=float(self.pilot.heights.sum()*self.pilot.CELL**2),
                    exit_classification=self.exit_classification, edge_confirmed=self.edge_confirmed,
                    continuous_no_flow_s=self.edge_time,
                    active=self.active, elapsed_s=self.elapsed)
