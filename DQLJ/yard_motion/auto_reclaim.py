"""Bounded strips and exposed-layer planning from current material and actual rig.

This controller schedules motion only. ReclaimPilot owns cutting, inventory and
the final collision guard. Completion means the selected strips, never a cleared layer.
"""
import copy
from concurrent.futures import ThreadPoolExecutor
import logging
import time
import uuid

import numpy as np

from .errors import MotionError
from .layer_coverage import describe_layer, layer_inventory

PLANNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='rc01-planner')


def pose_of(machine):
    return {name: axis.position for name, axis in machine.axes.items()}


class AutoReclaim:
    VERSION = 'rc01-auto-layers-v1'
    SPEEDS = {'travel': .5, 'slew': 1., 'luff': 1.}
    CUTTING_SLEW_SPEED = .35
    ACTIVE = {'PLANNING', 'RAISING', 'POSITIONING', 'ALIGNING', 'DRIVES_READY', 'APPROACHING',
              'SWEEPING', 'EDGE_CONFIRM', 'STOPPING', 'STRIP_STOPPING', 'RETRACTING',
              'PLANNING_NEXT', 'FEEDING', 'PLANNING_LAYER', 'CHANGE_LAYER'}

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
        self.strip_limit = 1
        self.completed_strips = []
        self.mode = 'single_strip'
        self.layer_index = self.layer_strips = 0
        self.layer_reports = []
        self.layer_targets = []
        self.layer_specs = []
        self.layer_base_m3 = 0.
        self.change_layer_pending = False
        self.settlement = None

    @property
    def active(self):
        return self.status in self.ACTIVE

    def command(self, machine, kind, payload):
        if self.active or machine.moving():
            raise MotionError('MACHINE_MOVING', '请先停止自动任务并停稳 RC01', 409)
        if kind == 'plan_auto_reclaim':
            if payload not in ({}, {'mode': 'two_strip_return'}, {'mode': 'two_layer_pilot'}) or not self.pilot.initialized:
                raise MotionError('INVALID_COMMAND', '请创建测试煤堆并选择有效取料模式', 422)
            self.mode = payload.get('mode', 'single_strip')
            self.strip_limit = 3 if self.mode == 'two_layer_pilot' else 2 if payload else 1
            self.completed_strips = []
            self.layer_index = self.layer_strips = 0
            self.layer_reports = []
            self.layer_targets = self.layer_specs = []
            self.change_layer_pending = False
            self.settlement = None
            worker = AutoReclaim(copy.deepcopy(self.pilot))
            worker.strip_limit = self.strip_limit
            worker.mode = self.mode
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
        if self.mode == 'two_layer_pilot':
            self.layer_specs = self.plan['layer_specs']
            self.layer_targets = [(layer_inventory(self.pilot, s['top_y'], s['bottom_y']) > 1e-10).tolist()
                                  for s in self.layer_specs]
            self.layer_base_m3 = self.pilot.reclaimed_m3
            self.pilot.cut_ceiling_y = self.plan['layer_top_y']
        self.status, self.reason = 'RAISING', 'SAFE_ENTRY'
        self._target(machine, 'luff', self.plan['safe_luff'])

    def _plan(self, machine, travel=None, floor=None, reverse=False, ceiling=None):
        p = self.pilot
        floor = p.GROUND + float(p.heights.max()) - .5 if floor is None else floor
        if floor <= p.GROUND:
            raise MotionError('NO_PLAN', '煤量不足以生成顶层单带计划', 409)
        travel_config = machine.axes['travel'].config
        travel = float(np.clip(np.average(p.x, weights=p.heights), travel_config['minimum'], travel_config['maximum'])) if travel is None else travel
        if not travel_config['minimum'] <= travel <= travel_config['maximum']:
            raise MotionError('NO_SAFE_FEED', '进车目标超出轨道限位', 409)
        safe = machine.axes['luff'].config['maximum']
        # Search safe poses with actual cutting contact above this layer floor.
        # 36 degrees spans one bucket pitch of this exported ten-bucket rig.
        minimum = machine.axes['luff'].config['minimum'] if self.mode == 'two_layer_pilot' else -4.
        for luff in np.arange(0., minimum-.01, -.5):
            if not machine.axes['luff'].config['minimum'] <= luff <= safe:
                continue
            run = []
            for slew in np.arange(-24., 24.01, 3.):
                pose = dict(travel=travel, slew=float(slew), luff=float(luff))
                usable = not p.collides(pose) and p.contact_depths(pose, 0, 36, .02, floor, ceiling).sum() > 1e-8
                if usable:
                    run.append(float(slew))
                else:
                    if len(run) >= 3:
                        break
                    run = []
            if len(run) < 3:
                continue
            start_slew, end_slew = (run[-1], run[0]) if reverse else (run[0], run[-1])
            start = dict(travel=travel, slew=start_slew, luff=float(luff))
            end = dict(start, slew=end_slew)
            if not p.path_clear(start, end):
                continue
            plan = dict(plan_id=uuid.uuid4().hex, scope='two_top_layer_strips' if self.strip_limit == 2 else 'single_top_layer_strip',
                        pile_id='RC01_TEST', material_version=p.version,
                        geometry_version=p.geometry['version'], layer_bottom_y=floor,
                        travel=travel, luff=float(luff), slew_start=start_slew, slew_end=end_slew,
                        safe_luff=safe, speed_limits=dict(self.SPEEDS, cutting_slew=self.CUTTING_SLEW_SPEED),
                        wheel_rpm=6., belt_m_s=2., remaining_m3=float(p.heights.sum()*p.CELL**2))
            plan['start_pose'] = pose_of(machine)
            if self.mode == 'two_layer_pilot':
                top = p.GROUND+float(p.heights.max()) if ceiling is None else ceiling
                plan.update(scope='two_layers_bounded', layer_index=self.layer_index, layer_top_y=top)
                if ceiling is None:
                    plan['layer_specs'] = [dict(top_y=top, bottom_y=floor),
                                           dict(top_y=floor, bottom_y=max(p.GROUND, floor-.5))]
            plan['wheel_path'] = [p.frame(dict(start, slew=float(a)))[2].tolist()
                                  for a in np.linspace(start_slew, end_slew, 25)]
            try:
                self._entry_path(machine, plan)
            except MotionError:
                continue
            return plan
        raise MotionError('NO_SAFE_STRIP', '未找到安全且有料的顶层回转带，请检查当前煤形与姿态', 409)

    def _next_plan(self, machine, previous):
        # Fixed, bounded candidate search; direction is selected by the real
        # material/geometry rather than inherited from the slew direction.
        for distance in (.1, .05, .025):
            for direction in (1, -1):
                try:
                    plan = self._plan(machine, previous['travel']+direction*distance,
                                      previous['layer_bottom_y'],
                                      reverse=previous['slew_end'] > previous['slew_start'],
                                      ceiling=previous.get('layer_top_y'))
                    plan['feed_m'] = plan['travel']-previous['travel']
                    return plan
                except MotionError:
                    continue
        raise MotionError('NO_SAFE_FEED', '缩短进车步长后仍无安全可切路径，请手动检查', 409)

    def _lower_plan(self, machine, previous, spec):
        for offset in (0., .1, -.1, .05, -.05, .025, -.025):
            try:
                plan = self._plan(machine, previous['travel']+offset, spec['bottom_y'],
                                  reverse=previous['slew_end'] > previous['slew_start'], ceiling=spec['top_y'])
                plan['feed_m'] = plan['travel']-previous['travel']
                return plan
            except MotionError:
                continue
        raise MotionError('NO_SAFE_LAYER', '下层无安全且露出的可切回转带，保留残煤', 409)

    def _close_layer(self, reason):
        spec = self.layer_specs[self.layer_index]
        remaining = float(layer_inventory(self.pilot, spec['top_y'], spec['bottom_y']).sum())
        self.layer_reports.append(describe_layer(self.pilot, spec, self.layer_targets[self.layer_index],
            max(0., self.pilot.reclaimed_m3-self.layer_base_m3),
            'COMPLETE' if remaining <= 1e-8 else 'PARTIAL', reason))

    def _submit_following_plan(self, machine, change_layer):
        if change_layer:
            self.layer_index += 1
            self.layer_strips = 0
            self.layer_base_m3 = self.pilot.reclaimed_m3
        worker = AutoReclaim(copy.deepcopy(self.pilot))
        worker.strip_limit, worker.mode, worker.layer_index = self.strip_limit, self.mode, self.layer_index
        if change_layer:
            self.future = PLANNER.submit(worker._lower_plan, copy.deepcopy(machine), copy.deepcopy(self.plan),
                                         dict(self.layer_specs[self.layer_index]))
        else:
            self.future = PLANNER.submit(worker._next_plan, copy.deepcopy(machine), copy.deepcopy(self.plan))
        self.planning_started = time.monotonic()
        self.status = 'PLANNING_LAYER' if change_layer else 'PLANNING_NEXT'
        self.reason = 'EXPOSED_LOWER_COAL_SEARCH' if change_layer else 'UPDATED_COAL_SAFE_FEED_SEARCH'

    def _finish_strip(self, machine):
        self.completed_strips.append(dict(travel=self.plan['travel'],
            slew_start=self.plan['slew_start'], slew_end=self.plan['slew_end'],
            layer_bottom_y=self.plan['layer_bottom_y'], end_reclaimed_m3=self.pilot.reclaimed_m3,
            layer_index=self.layer_index,
            exit_classification=self.exit_classification, edge_confirmed=self.edge_confirmed))
        if self.mode == 'two_layer_pilot':
            self.layer_strips += 1
            spec = self.layer_specs[self.layer_index]
            clear = layer_inventory(self.pilot, spec['top_y'], spec['bottom_y']).sum() <= 1e-8
            if clear or self.layer_strips >= self.strip_limit:
                self._close_layer('LAYER_MATERIAL_REMOVED' if clear else 'STRIP_BUDGET_REACHED')
                self.change_layer_pending = self.layer_index+1 < len(self.layer_specs)
                self.stop(machine, 'STRIP_STOPPING' if self.change_layer_pending else 'STOPPING',
                          'SAFE_LAYER_EXIT' if self.change_layer_pending else 'TWO_LAYER_PILOT_COMPLETE_WITH_REPORT')
            else:
                self.change_layer_pending = False
                self.stop(machine, 'STRIP_STOPPING', 'SAFE_EXIT_BEFORE_FEED')
            return
        if len(self.completed_strips) < self.strip_limit:
            self.stop(machine, 'STRIP_STOPPING', 'SAFE_EXIT_BEFORE_FEED')
        else:
            self.stop(machine, 'STOPPING', 'TWO_STRIPS_COMPLETE' if self.strip_limit == 2 else 'SINGLE_STRIP_COMPLETE')

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
        if self.status in ('PLANNING', 'PLANNING_NEXT', 'PLANNING_LAYER'):
            if time.monotonic()-self.planning_started > 30:
                self.stop(machine, 'FAILED', 'PLAN_TIMEOUT')
            return
        self.elapsed += dt
        if self.elapsed > 180*self.strip_limit*(2 if self.mode == 'two_layer_pilot' else 1):
            self.stop(machine, 'FAILED', 'ACTION_TIMEOUT')

    def after_step(self, machine, dt):
        self.sync(machine)
        if not self.active:
            return
        p = self.pilot
        if self.job_id:
            self.taken = max(0., p.reclaimed_m3-self.base_m3)
        if self.status not in ('PLANNING', 'PLANNING_NEXT', 'PLANNING_LAYER', 'SWEEPING', 'EDGE_CONFIRM', 'STOPPING', 'STRIP_STOPPING'):
            self.no_progress = self.no_progress+dt if p.blocked else 0.
            if self.no_progress > 2:
                self.stop(machine, 'BLOCKED', 'ENTRY_PATH_BLOCKED')
                return
        if self.status == 'RAISING' and machine.axes['luff'].mode == 'idle':
            self.status = 'POSITIONING'
            self._target(machine, 'travel', self.plan['travel'])
        elif self.status in ('POSITIONING', 'FEEDING') and machine.axes['travel'].mode == 'idle':
            self.status = 'ALIGNING'
            self._target(machine, 'slew', self.plan['slew_start'])
        elif self.status == 'ALIGNING' and machine.axes['slew'].mode == 'idle':
            self.status = 'DRIVES_READY'
            machine.wheel.target_speed = self.plan['wheel_rpm']
            machine.belt.target_speed = self.plan['belt_m_s']
        elif self.status == 'DRIVES_READY' and machine.wheel.speed >= 5.99 and machine.belt.speed >= 1.99:
            self.status = 'CHANGE_LAYER' if self.mode == 'two_layer_pilot' and self.layer_index > 0 else 'APPROACHING'
            self._target(machine, 'luff', self.plan['luff'])
        elif self.status in ('APPROACHING', 'CHANGE_LAYER') and machine.axes['luff'].mode == 'idle':
            self.status, self.reason = 'SWEEPING', 'SAFE_SHALLOW_CUT'
            p.enabled = True
            self._target(machine, 'slew', self.plan['slew_end'])
        elif self.status == 'SWEEPING':
            self.no_progress = self.no_progress+dt if p.blocked and p.actual_m3_s <= 1e-10 else 0.
            if self.no_progress > 5:
                self.stop(machine, 'BLOCKED', 'COAL_GUARD_NO_PROGRESS')
            elif machine.axes['slew'].mode == 'idle':
                self.status, self.reason = 'EDGE_CONFIRM', 'PLANNED_STRIP_EXIT'
                direction = 1 if self.plan['slew_end'] > self.plan['slew_start'] else -1
                ahead = dict(pose_of(machine), slew=self.plan['slew_end']+direction*3.)
                if p.collides(ahead):
                    self.exit_classification = 'GEOMETRY_LIMIT'
                elif p.contact_depths(ahead, 0, 36, .02, self.plan['layer_bottom_y'], self.plan.get('layer_top_y')).sum() > 1e-8:
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
                self._finish_strip(machine)
            elif self.edge_time >= pitch_seconds:
                self.edge_confirmed = True
                self._finish_strip(machine)
            elif self.exit_elapsed > 20:
                self.stop(machine, 'BLOCKED', 'NO_STABLE_EDGE')
        elif self.status == 'STRIP_STOPPING' and not machine.moving():
            self.status = 'RETRACTING'
            self._target(machine, 'luff', self.plan['safe_luff'])
        elif self.status == 'RETRACTING' and machine.axes['luff'].mode == 'idle':
            self._submit_following_plan(machine, self.change_layer_pending)
        elif self.status == 'STOPPING' and not machine.moving():
            self.status = 'COMPLETED'
            self.settlement = self._build_coverage_report()

    def stop(self, machine, status, reason):
        # Stop drives and debit. STRIP_STOPPING deliberately continues the
        # active job only after all motion has settled; other terminal states
        # discard further scheduling and require explicit replanning.
        machine.stop()
        self.pilot.enabled = False
        self.pilot.actual_m3_s = 0.
        self.pilot.cut_floor_y = None
        self.pilot.cut_ceiling_y = None
        self.status, self.reason = status, reason
        if self.future:
            self.future.cancel()
            self.future = None
        if not self.active and self.settlement is None:
            self.settlement = self._build_coverage_report()

    def sync(self, machine):
        if self.active and (not machine.lease or machine.lease['state'] != 'owned' or machine.estop):
            self.stop(machine, 'ESTOP' if machine.estop else 'CONTROL_LOST', 'ESTOP' if machine.estop else 'CONTROL_REQUIRED')
        if self.status in ('PLANNING', 'PLANNING_NEXT', 'PLANNING_LAYER') and self.future and self.future.done():
            next_strip = self.status != 'PLANNING'
            lower_search = self.status == 'PLANNING_LAYER'
            future = self.future
            self.future = None
            try:
                plan = future.result()
                if next_strip:
                    if plan['material_version'] != self.pilot.version or plan['start_pose'] != pose_of(machine):
                        raise MotionError('STALE_PLAN', '进车规划期间煤形或姿态已变化', 409)
                    self.plan = plan
                    self.pilot.cut_floor_y = plan['layer_bottom_y']
                    self.pilot.cut_ceiling_y = plan.get('layer_top_y')
                    self.no_progress = self.edge_time = self.exit_elapsed = 0.
                    self.exit_classification = None
                    self.edge_confirmed = False
                    self.status, self.reason = 'FEEDING', 'SAFE_TRACK_FEED'
                    self._target(machine, 'travel', plan['travel'])
                else:
                    self.plan = plan
                    self.status, self.reason = 'PLANNED', 'EXPLICIT_START_REQUIRED'
            except Exception as error:
                logging.getLogger(__name__).exception('RC01 read-only planning failed')
                code = getattr(error, 'code', 'PLAN_FAILED')
                if next_strip and self.mode == 'two_layer_pilot' and code in ('NO_SAFE_FEED','NO_SAFE_LAYER'):
                    self._close_layer(code)
                    if not lower_search and self.layer_index+1 < len(self.layer_specs):
                        self._submit_following_plan(machine, True)
                    else:
                        self.stop(machine, 'BLOCKED', code)
                else:
                    self.stop(machine, 'BLOCKED' if next_strip else 'FAILED', code)

    def coverage_report(self):
        return copy.deepcopy(self.settlement) if self.settlement is not None else self._build_coverage_report()

    def _build_coverage_report(self):
        if not self.layer_specs:
            return None
        layers = copy.deepcopy(self.layer_reports)
        while len(layers) < len(self.layer_specs):
            index = len(layers)
            current = index == self.layer_index
            layers.append(describe_layer(self.pilot, self.layer_specs[index], self.layer_targets[index],
                max(0., self.taken-sum(s['reclaimed_m3'] for s in layers)) if current else 0.,
                ('IN_PROGRESS' if self.active else 'STOPPED') if current else 'NOT_STARTED',
                self.reason if current else 'LAYER_NOT_STARTED'))
        return dict(layers=layers, settled=not self.active, material_version=self.pilot.version,
                    remaining_m3=float(self.pilot.heights.sum()*self.pilot.CELL**2),
                    below_planned_layers_m3=float(np.minimum(self.pilot.heights,
                    max(0., self.layer_specs[-1]['bottom_y']-self.pilot.GROUND)).sum()*self.pilot.CELL**2))

    def snapshot(self):
        return dict(version=self.VERSION, status=self.status, reason=self.reason,
                    plan=copy.deepcopy(self.plan), job_id=self.job_id,
                    job_reclaimed_m3=self.taken,
                    pile_remaining_m3=float(self.pilot.heights.sum()*self.pilot.CELL**2),
                    exit_classification=self.exit_classification, edge_confirmed=self.edge_confirmed,
                    continuous_no_flow_s=self.edge_time,
                    completed_strips=copy.deepcopy(self.completed_strips), strip_limit=self.strip_limit,
                    layer_index=self.layer_index, coverage_report=self.coverage_report(),
                    active=self.active, elapsed_s=self.elapsed)
