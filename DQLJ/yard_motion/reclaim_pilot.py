"""RC01 preview-only volume pilot. Fixed cell columns, no density or slope solver.

Geometry is exported from the actual preview rig. Mesh bounds conservatively
protect the boom; a rotation-invariant cylinder protects the wheel body. Cutting
uses the 40 current tooth bounds and 10 open scoop bounds, with per-step depth
and volume demo limits. These are conservative mesh bounds, not particle physics.
"""
import json
import math
from pathlib import Path

import numpy as np

from .errors import MotionError
from .world import World
from .auto_reclaim import AutoReclaim


def rotation_y(angle):
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rotation_z(angle):
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


class ReclaimPilot:
    VERSION = 'rc01-coal-pilot-v1'
    # Located in the existing gap between the middle and east static piles.
    CELL = .5
    X, Z, NX, NZ, GROUND = -335., -216., 28, 24, .18
    MAX_FLOW_M3_S = .4  # demonstrator limit, not a surveyed machine capacity
    MAX_DEPTH_M_S = .3
    CLEARANCE = .025

    def __init__(self, scene):
        self.geometry = json.loads((Path(__file__).resolve().parents[1] /
                                    'config/rc01-preview-geometry.json').read_text(encoding='utf-8'))
        self.scene = scene
        self.initialized = self.enabled = False
        self.version = 0
        self.heights = np.zeros(self.NX * self.NZ)
        ix, iz = np.meshgrid(np.arange(self.NX), np.arange(self.NZ))
        self.x = self.X + (ix.ravel() + .5) * self.CELL
        self.z = self.Z + (iz.ravel() + .5) * self.CELL
        self.initial_m3 = self.reclaimed_m3 = 0.
        self.actual_m3_s = 0.
        self.cut_floor_y = None
        self.cut_ceiling_y = None
        self.reason = 'NOT_INITIALIZED'
        self.blocked = False
        self.protected_centers = np.array([b['center'] for b in self.geometry['protected_boom_boxes']])
        self.protected_vectors = np.array([b['axes'] for b in self.geometry['protected_boom_boxes']])
        self.cutting_boxes = self.geometry['teeth'] + self.geometry['scoops']
        self.cutting_radius = max(np.linalg.norm(np.array(b['center'])[:2])+
                                  sum(np.linalg.norm(np.array(v)[:2]) for v in b['axes'])
                                  for b in self.cutting_boxes) * self.geometry['root_scale'] * self.geometry['wheel_scale'][0]

    def frame(self, pose):
        yaw = rotation_y(self.scene['yaw'] - 90 - pose['slew'])
        matrix = yaw @ rotation_z(pose['luff'])
        hinge = np.array([pose['travel'], self.scene['y'] +
                          self.geometry['root_scale'] * self.geometry['hinge_height'], self.scene['z']])
        center = hinge + matrix @ (np.array(self.geometry['wheel_center_boom_local']) * self.geometry['root_scale'])
        return matrix, hinge, center

    def reset(self, pose):
        # Flat-topped trapezoidal test pile, fixed in world metres.
        candidate = 4.8 * np.minimum(np.clip((6 - np.abs(self.x + 328)) / 2, 0, 1),
                                     np.clip((5 - np.abs(self.z + 210)) / 3, 0, 1))
        old = self.heights
        self.heights = candidate
        if self.collides(pose):
            self.heights = old
            raise MotionError('PILE_COLLISION', '恢复位置与 RC01 相交，请先退出测试区', 409)
        self.initialized, self.enabled = True, False
        self.cut_floor_y = self.cut_ceiling_y = None
        self.initial_m3 = float(candidate.sum() * self.CELL**2)
        self.reclaimed_m3 = self.actual_m3_s = 0.
        self.version += 1
        self.reason = 'READY'
        self.blocked = False

    def path_clear(self, before, after):
        # Check intermediate poses too, including instantaneous reset commands.
        if before == after:
            return True
        a = self.frame(before)[2]
        b = self.frame(after)[2]
        count = max(1, math.ceil(float(np.linalg.norm(b-a))/.02),
                    math.ceil(abs(after['slew']-before['slew'])/.1),
                    math.ceil(abs(after['luff']-before['luff'])/.1))
        for step in range(1, count+1):
            pose = {name: before[name]+(after[name]-before[name])*step/count for name in before}
            if self.collides(pose):
                return False
        return True

    def _box_cells(self, box, matrix, origin, scale, indices):
        """Conservative exact SAT: exported mesh OBB versus solid cell columns."""
        center = origin + matrix @ (np.array(box['center']) * scale)
        vectors = (matrix @ (np.array(box['axes']) * scale).T).T
        extents = np.linalg.norm(vectors, axis=1)
        axes = vectors / np.maximum(extents[:, None], 1e-12)
        centers = np.column_stack((self.x[indices], self.GROUND + self.heights[indices] / 2, self.z[indices]))
        cell_extents = np.column_stack((np.full(len(indices), self.CELL/2),
                                       self.heights[indices]/2, np.full(len(indices), self.CELL/2)))
        delta = centers - center
        test_axes = list(np.eye(3)) + list(axes)
        test_axes += [np.cross(a, b) for a in axes for b in np.eye(3)]
        mask = np.ones(len(indices), dtype=bool)
        for axis in test_axes:
            if np.linalg.norm(axis) < 1e-10:
                continue
            extent = np.abs(axes @ axis) @ extents
            mask &= np.abs(delta @ axis) <= extent + cell_extents @ np.abs(axis) + self.CLEARANCE
        return indices[mask], center, vectors

    def collides(self, pose):
        indices = np.flatnonzero(self.heights > 1e-10)
        if not len(indices):
            return False
        matrix, hinge, center = self.frame(pose)
        # The wheel remains vertical under luffing; rotation does not change its body cylinder.
        yaw = math.radians(self.scene['yaw'] - 90 - pose['slew'])
        c, s = math.cos(yaw), math.sin(yaw)
        q = (self.x[indices]-center[0])*c - (self.z[indices]-center[2])*s
        axial = (self.x[indices]-center[0])*s + (self.z[indices]-center[2])*c
        inflation = self.CELL/2 * (abs(c)+abs(s)) + self.CLEARANCE
        ws = self.geometry['root_scale'] * self.geometry['wheel_scale'][0]
        radius = self.geometry['body_radius_wheel_local'] * ws
        distance = np.maximum(0, np.abs(q)-inflation)
        low = center[1] - np.sqrt(np.maximum(0, radius**2-distance**2)) - self.CLEARANCE
        high = center[1] + np.sqrt(np.maximum(0, radius**2-distance**2)) + self.CLEARANCE
        inside = ((distance <= radius) &
                  (axial >= self.geometry['body_axial_min_wheel_local']*ws-inflation) &
                  (axial <= self.geometry['body_axial_max_wheel_local']*ws+inflation) &
                  (self.GROUND+self.heights[indices] > low) & (self.GROUND < high))
        if inside.any():
            return True
        centers = hinge + (self.protected_centers * self.geometry['root_scale']) @ matrix.T
        extents = np.abs((self.protected_vectors * self.geometry['root_scale']) @ matrix.T).sum(axis=1)
        candidates = np.flatnonzero((centers[:,0]+extents[:,0] >= self.x[indices].min()-self.CELL/2) &
                                    (centers[:,0]-extents[:,0] <= self.x[indices].max()+self.CELL/2) &
                                    (centers[:,2]+extents[:,2] >= self.z[indices].min()-self.CELL/2) &
                                    (centers[:,2]-extents[:,2] <= self.z[indices].max()+self.CELL/2) &
                                    (centers[:,1]-extents[:,1] <= self.GROUND+self.heights[indices].max()+self.CLEARANCE))
        for index in candidates:
            box = self.geometry['protected_boom_boxes'][index]
            # Broad phase avoids SAT for the many parts far from this small pile.
            local_center = hinge + matrix @ (np.array(box['center']) * self.geometry['root_scale'])
            extent = np.sum(np.abs(matrix @ (np.array(box['axes'])*self.geometry['root_scale']).T), axis=1)
            relevant = indices[(np.abs(self.x[indices]-local_center[0]) <= extent[0]+self.CELL/2+self.CLEARANCE) &
                               (np.abs(self.z[indices]-local_center[2]) <= extent[2]+self.CELL/2+self.CLEARANCE) &
                               (self.GROUND+self.heights[indices] >= local_center[1]-extent[1]-self.CLEARANCE)]
            if len(relevant) and len(self._box_cells(box, matrix, hinge, self.geometry['root_scale'], relevant)[0]):
                return True
        return False

    def contact_depths(self, pose, phase_before, phase_after, dt, floor_y=None, ceiling_y=None):
        depths = np.zeros_like(self.heights)
        eligible = self.heights > 1e-10
        if floor_y is not None:
            eligible &= self.GROUND+self.heights > floor_y
        if ceiling_y is not None:
            # A column is solid: lower-layer cutting may not debit buried coal
            # through an upper column. Its complete current surface must be exposed.
            eligible &= self.GROUND+self.heights <= ceiling_y+1e-8
        indices = np.flatnonzero(eligible)
        if not len(indices):
            return depths
        matrix, _, center = self.frame(pose)
        if (center[1]-self.cutting_radius > self.GROUND+self.heights[indices].max() or
                center[0]+self.cutting_radius < self.x[indices].min()-self.CELL/2 or
                center[0]-self.cutting_radius > self.x[indices].max()+self.CELL/2 or
                center[2]+self.cutting_radius < self.z[indices].min()-self.CELL/2 or
                center[2]-self.cutting_radius > self.z[indices].max()+self.CELL/2):
            return depths
        ws = self.geometry['root_scale'] * self.geometry['wheel_scale'][0]
        for phase in np.linspace(phase_before, phase_after, max(2, math.ceil(abs(phase_after-phase_before))+1)):
            wheel_matrix = matrix @ rotation_z(phase)
            for box in self.cutting_boxes:
                tooth_center = center + wheel_matrix @ (np.array(box['center'])*ws)
                extent = np.sum(np.abs(wheel_matrix @ (np.array(box['axes'])*ws).T), axis=1)
                relevant = indices[(np.abs(self.x[indices]-tooth_center[0]) <= extent[0]+self.CELL/2) &
                                   (np.abs(self.z[indices]-tooth_center[2]) <= extent[2]+self.CELL/2) &
                                   (self.GROUND+self.heights[indices] >= tooth_center[1]-extent[1])]
                if not len(relevant):
                    continue
                contacts = self._box_cells(box, wheel_matrix, center, ws, relevant)[0]
                depth = np.minimum(self.MAX_DEPTH_M_S*dt,
                                   np.maximum(0, np.minimum(self.GROUND+self.heights[contacts],tooth_center[1]+extent[1])-
                                              max(self.GROUND,tooth_center[1]-extent[1])))
                depths[contacts] = np.maximum(depths[contacts], depth)
        if floor_y is not None:
            depths = np.minimum(depths, np.maximum(0, self.GROUND+self.heights-floor_y))
        return depths

    def cut(self, pose, phase_before, phase_after, dt):
        depths = self.contact_depths(pose, phase_before, phase_after, dt, self.cut_floor_y, self.cut_ceiling_y)
        volume = float(depths.sum()*self.CELL**2)
        if volume > self.MAX_FLOW_M3_S*dt:
            depths *= self.MAX_FLOW_M3_S*dt / volume
        depths = np.minimum(depths, self.heights)
        actual = float(depths.sum()*self.CELL**2)
        if actual > 0:
            self.heights -= depths
            self.reclaimed_m3 += actual
            self.version += 1
        return actual

    def step(self, machine, before, phase_before, dt):
        self.actual_m3_s = 0.
        self.blocked = False
        if not self.initialized:
            return
        owned = machine.lease and machine.lease['state'] == 'owned'
        if not owned or machine.estop:
            self.enabled = False
        if self.enabled and owned and not machine.estop and machine.wheel.speed > .001 and machine.belt.speed > .001:
            actual = self.cut(before, phase_before, machine.wheel.distance, dt)
            self.actual_m3_s = actual / dt
            self.reason = 'CUTTING' if actual else 'NO_CONTACT'
        else:
            self.reason = ('ESTOP' if machine.estop else 'CONTROL_REQUIRED' if not owned else
                           'PAUSED' if not self.enabled else 'WHEEL_STOPPED' if machine.wheel.speed <= .001 else 'BELT_STOPPED')
        after = {name: axis.position for name, axis in machine.axes.items()}
        if not self.path_clear(before, after):
            # Resolve axes separately so a retained inward target cannot block
            # raising/retreating on another axis. Check the combined path as well.
            accepted = dict(before)
            for name in ('luff', 'slew', 'travel'):
                candidate = dict(accepted, **{name: after[name]})
                if self.path_clear(before, candidate):
                    accepted = candidate
                else:
                    machine.axes[name].velocity = 0.
            for name, axis in machine.axes.items():
                axis.position = accepted[name]
            self.blocked = True
            self.reason = 'COAL_GUARD'
        # The prior pose was accepted previously. Cutting only lowers columns,
        # so it cannot turn that prior safe pose into a collision.

    def snapshot(self):
        return dict(version=self.VERSION, geometry_version=self.geometry['version'], initialized=self.initialized,
                    enabled=self.enabled, material_version=self.version, blocked=self.blocked, reason=self.reason,
                    grid=dict(origin_x=self.X, origin_z=self.Z, cell_size=self.CELL, cells_x=self.NX, cells_z=self.NZ,
                              ground=self.GROUND), heights=self.heights.tolist() if self.initialized else [],
                    initial_m3=self.initial_m3, remaining_m3=float(self.heights.sum()*self.CELL**2),
                    reclaimed_m3=self.reclaimed_m3, actual_m3_s=self.actual_m3_s,
                    wheel_body=dict(radius_model=self.geometry['body_radius_wheel_local']*self.geometry['wheel_scale'][0],
                                    axial_min_model=self.geometry['body_axial_min_wheel_local']*self.geometry['wheel_scale'][0],
                                    axial_max_model=self.geometry['body_axial_max_wheel_local']*self.geometry['wheel_scale'][0]))


class PreviewWorld(World):
    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.pilot = ReclaimPilot(self.machines['RC01'].config['scene'])
        self.auto = AutoReclaim(self.pilot)

    def _apply(self, machine, kind, payload):
        if kind in ('pause_auto_reclaim', 'cancel_auto_reclaim', 'take_manual_control'):
            if machine.config['machine_id'] != 'RC01' or payload:
                raise MotionError('INVALID_COMMAND', '自动试验仅支持 RC01 且参数应为空', 422)
            self.auto.stop(machine, 'PAUSED' if kind != 'cancel_auto_reclaim' else 'CANCELLED', kind)
            return
        if kind in ('plan_auto_reclaim', 'start_auto_reclaim'):
            if machine.config['machine_id'] != 'RC01':
                raise MotionError('PILOT_MACHINE', '自动试验仅支持 RC01', 422)
            self.auto.command(machine, kind, payload)
            return
        if machine.config['machine_id'] == 'RC01' and self.auto.active and (
                kind in ('set_targets', 'jog', 'reset', 'reset_reclaim_pilot', 'set_reclaim_pilot') or
                kind in ('set_wheel', 'set_belt') and payload.get('speed') != 0):
            raise MotionError('AUTO_ACTIVE', '自动任务执行中，请先暂停或手动接管', 409)
        if kind in ('reset_reclaim_pilot', 'set_reclaim_pilot'):
            if machine.config['machine_id'] != 'RC01':
                raise MotionError('PILOT_MACHINE', '试验仅支持 RC01', 422)
            if kind == 'reset_reclaim_pilot':
                if payload or machine.moving():
                    raise MotionError('MACHINE_MOVING', '请先停稳 RC01，再恢复测试煤堆', 409)
                self.pilot.reset({n:a.position for n,a in machine.axes.items()})
                self.auto = AutoReclaim(self.pilot)
                self.auto.reason = 'PILE_RESET'
            else:
                if set(payload) != {'enabled'} or type(payload['enabled']) is not bool:
                    raise MotionError('INVALID_COMMAND', '试验启用参数无效', 422)
                if not self.pilot.initialized:
                    raise MotionError('NOT_INITIALIZED', '请先创建测试煤堆', 409)
                self.pilot.enabled = payload['enabled']
                self.pilot.actual_m3_s = 0.
            return
        if kind == 'reset' and machine.config['machine_id'] == 'RC01' and self.pilot.initialized:
            pose = {n:a.config['initial'] for n,a in machine.axes.items()}
            before = {n:a.position for n,a in machine.axes.items()}
            if not self.pilot.path_clear(before, pose):
                raise MotionError('PILE_COLLISION', '复位路径被煤堆占用，请先抬臂退出测试区', 409)
        super()._apply(machine, kind, payload)
        if machine.config['machine_id'] == 'RC01' and (kind in ('stop', 'estop', 'reset') or
                kind in ('set_wheel','set_belt') and payload.get('speed') == 0):
            self.pilot.enabled = False
            self.pilot.actual_m3_s = 0.
            if self.auto.active:
                self.auto.stop(machine, 'ESTOP' if kind == 'estop' else 'PAUSED', kind)

    def advance(self, dt):
        if not math.isfinite(dt) or not 0 <= dt <= 1:
            raise ValueError('Step must be between 0 and 1 second')
        with self.lock:
            remaining = dt
            while remaining > 1e-10:
                h = min(.02, remaining)
                remaining -= h
                machine = self.machines['RC01']
                before = {n:a.position for n,a in machine.axes.items()}
                phase = machine.wheel.distance
                self.auto.before_step(machine, h)
                super().advance(h)
                self.pilot.step(machine, before, phase, h)
                self.auto.after_step(machine, h)

    def state(self):
        with self.lock:
            state = super().state()
            machine = self.machines['RC01']
            self.auto.sync(machine)
            state['machines']['RC01'] = self._snapshot(machine)
            if not machine.lease or machine.lease['state'] != 'owned':
                self.pilot.enabled = False
                self.pilot.actual_m3_s = 0.
            state['reclaim_pilot'] = self.pilot.snapshot()
            pose = {n:a.position for n,a in machine.axes.items()}
            state['reclaim_pilot']['wheel_center'] = self.pilot.frame(pose)[2].tolist()
            state['auto_reclaim'] = self.auto.snapshot()
            return state
