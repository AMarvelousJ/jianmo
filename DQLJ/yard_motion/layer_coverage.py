"""Material coverage, not inferred from drive travel or elapsed time."""
import numpy as np


def layer_inventory(pilot, top_y, bottom_y):
    surface = pilot.GROUND+pilot.heights
    return np.clip(surface-bottom_y, 0, top_y-bottom_y)*pilot.CELL**2


def describe_layer(pilot, spec, initial_cells, reclaimed, status, reason):
    volume = layer_inventory(pilot, spec['top_y'], spec['bottom_y'])
    surface = pilot.GROUND+pilot.heights
    target = np.array(initial_cells, dtype=bool)
    cleared = target & (volume <= 1e-10)
    occluded = target & (volume > 1e-10) & (surface > spec['top_y']+1e-8)
    pending = target & ~cleared & ~occluded
    states = np.full(len(surface), 'NOT_IN_LAYER', dtype=object)
    states[cleared] = 'CLEARED'
    states[occluded] = 'UPPER_LAYER_REMAINS'
    states[pending] = 'PENDING'
    return dict(top_y=spec['top_y'], bottom_y=spec['bottom_y'],
                material_version=pilot.version, remaining_m3=float(volume.sum()),
                reclaimed_m3=reclaimed, status=status, reason=reason,
                target_cells=int(target.sum()), cleared_cells=int(cleared.sum()),
                pending_cells=int(pending.sum()), upper_blocked_cells=int(occluded.sum()),
                cell_states=states.tolist())
