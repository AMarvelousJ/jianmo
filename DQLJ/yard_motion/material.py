"""Coal material domain: grid pile shape, zone classification, and quantity ledger.

Ground elevation and coal thickness are stored separately per cell; thickness is
never negative. In-zone and spilled inventories are maintained incrementally so
the conservation identity (initial + received - output == in-zone + spilled) is
checkable from every state snapshot without scanning the grid.
"""
import json
import math
from collections import namedtuple
from pathlib import Path

from .errors import MotionError, finite

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/material.json"

_ZONE_YARD, _ZONE_SPILL, _ZONE_OUTSIDE = 2, 1, 0

Rect = namedtuple("Rect", "x0 x1 z0 z1")


def _rect(config, key):
    rect = config[key]
    x0, x1 = rect["x"]
    z0, z1 = rect["z"]
    if not (x0 < x1 and z0 < z1):
        raise ValueError("Invalid %s rectangle" % key)
    return Rect(x0, x1, z0, z1)


class MaterialDomain:
    def __init__(self, config=None):
        self.config = config or json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))
        self._validate_config()
        grid = self.config["grid"]
        self.cell = grid["cell_size"]
        self.origin_x, self.origin_z = grid["origin_x"], grid["origin_z"]
        self.nx, self.nz = grid["cells_x"], grid["cells_z"]
        self.cell_area = self.cell * self.cell
        self.coal = self.config["coal"]
        elevation = self.config["ground"]["elevation"]
        self.ground = [elevation] * (self.nx * self.nz)
        self.heights = [0.0] * (self.nx * self.nz)
        self.zone_code = self._classify_cells()
        self.scene = "uninitialized"
        self.version = 0
        self.ledger = dict(initial_m3=0.0, received_m3=0.0, output_m3=0.0)
        self.in_zone_m3 = 0.0
        self.spilled_m3 = 0.0

    def _validate_config(self):
        c = self.config
        for key in ("version", "source", "grid", "domain", "zones", "ground", "coal"):
            if key not in c:
                raise ValueError("Missing material config section: %s" % key)
        grid = c["grid"]
        for key in ("cell_size", "cells_x", "cells_z"):
            if not isinstance(grid.get(key), (int, float)) or isinstance(grid.get(key), bool) or not math.isfinite(grid[key]) or grid[key] <= 0:
                raise ValueError("Invalid material grid configuration")
        for key in ("origin_x", "origin_z"):
            if not isinstance(grid.get(key), (int, float)) or isinstance(grid.get(key), bool) or not math.isfinite(grid[key]):
                raise ValueError("Invalid material grid configuration")
        domain = _rect(c, "domain")
        expected_x = domain.x1 - domain.x0
        expected_z = domain.z1 - domain.z0
        if abs(grid["cells_x"] * grid["cell_size"] - expected_x) > 1e-6 or abs(grid["cells_z"] * grid["cell_size"] - expected_z) > 1e-6:
            raise ValueError("Grid cell count does not tile the domain")
        yard = _rect(c["zones"], "yard")
        spill = _rect(c["zones"], "spill")
        if not (spill.x0 <= yard.x0 and yard.x1 <= spill.x1 and spill.z0 <= yard.z0 and yard.z1 <= spill.z1):
            raise ValueError("Yard zone must lie inside the spill zone")
        if not (domain.x0 <= spill.x0 and spill.x1 <= domain.x1 and domain.z0 <= spill.z0 and spill.z1 <= domain.z1):
            raise ValueError("Spill zone must lie inside the domain")
        for name in ("yard", "spill"):
            rect = c["zones"][name]
            for axis, origin in (("x", grid["origin_x"]), ("z", grid["origin_z"])):
                for edge in rect[axis]:
                    if abs((edge - origin) / grid["cell_size"] - round((edge - origin) / grid["cell_size"])) > 1e-6:
                        raise ValueError("Zone edges must align to the grid")
        coal = c["coal"]
        for key in ("density_t_per_m3", "repose_angle_deg", "max_height", "flow_capability_t_per_h", "deposit_sigma_m"):
            if not isinstance(coal.get(key), (int, float)) or isinstance(coal.get(key), bool) or not math.isfinite(coal[key]) or coal[key] <= 0:
                raise ValueError("Invalid coal parameter: %s" % key)
        if c["ground"]["elevation"] < 0 or not math.isfinite(c["ground"]["elevation"]):
            raise ValueError("Invalid ground elevation")

    def _classify_cells(self):
        zones = self.config["zones"]
        yard = _rect(zones, "yard")
        spill = _rect(zones, "spill")
        codes = bytearray(self.nx * self.nz)
        for j in range(self.nz):
            z = self.origin_z + (j + 0.5) * self.cell
            for i in range(self.nx):
                x = self.origin_x + (i + 0.5) * self.cell
                if yard.x0 <= x <= yard.x1 and yard.z0 <= z <= yard.z1:
                    codes[j * self.nx + i] = _ZONE_YARD
                elif spill.x0 <= x <= spill.x1 and spill.z0 <= z <= spill.z1:
                    codes[j * self.nx + i] = _ZONE_SPILL
        return codes

    def init_scene(self, mode):
        if mode not in ("empty", "preset"):
            raise MotionError("INVALID_SCENE", "未知物料场景模式", 422)
        self.heights = [0.0] * (self.nx * self.nz)
        self.in_zone_m3 = 0.0
        self.spilled_m3 = 0.0
        if mode == "preset":
            self._rasterize_preset()
        self.scene = mode
        self.ledger = dict(initial_m3=self.in_zone_m3 + self.spilled_m3, received_m3=0.0, output_m3=0.0)
        self.version += 1

    def _rasterize_preset(self):
        p = self.config["preset"]
        run = p["height"] / math.tan(math.radians(self.coal["repose_angle_deg"]))
        half_length = p["length_x"] / 2
        half_base, half_top = p["base_width_z"] / 2, p["top_width_z"] / 2
        i0 = max(0, int((p["center_x"] - half_length - run - self.origin_x) / self.cell))
        i1 = min(self.nx - 1, int((p["center_x"] + half_length + run - self.origin_x) / self.cell))
        j0 = max(0, int((p["center_z"] - half_base - self.origin_z) / self.cell))
        j1 = min(self.nz - 1, int((p["center_z"] + half_base - self.origin_z) / self.cell))
        for j in range(j0, j1 + 1):
            z = self.origin_z + (j + 0.5) * self.cell
            dz = abs(z - p["center_z"])
            if dz <= half_top:
                lateral = 1.0
            elif dz <= half_base:
                lateral = (half_base - dz) / (half_base - half_top)
            else:
                continue
            for i in range(i0, i1 + 1):
                x = self.origin_x + (i + 0.5) * self.cell
                dx = abs(x - p["center_x"])
                if dx > half_length:
                    continue
                longitudinal = 1.0 if dx <= half_length - run else (half_length - dx) / run
                height = p["height"] * lateral * longitudinal
                if height > 0:
                    index = j * self.nx + i
                    if self.zone_code[index] == _ZONE_OUTSIDE:
                        # clipped: heights outside the spill zone would be reclaimable
                        # without ever entering the ledger, breaking conservation
                        continue
                    self.heights[index] = height
                    if self.zone_code[index] == _ZONE_YARD:
                        self.in_zone_m3 += height * self.cell_area
                    else:
                        self.spilled_m3 += height * self.cell_area

    def _require_scene(self):
        if self.scene == "uninitialized":
            raise MotionError("MATERIAL_UNINITIALIZED", "物料场景尚未初始化", 409)

    def _require_in_domain(self, x, z):
        domain = _rect(self.config, "domain")
        if not (domain.x0 <= x <= domain.x1 and domain.z0 <= z <= domain.z1):
            raise MotionError("MATERIAL_OUT_OF_DOMAIN", "作用点在物料域之外", 422)

    def _window_cells(self, x, z, radius):
        """Yield (index, centre_x, centre_z) for every cell in the bounded search window."""
        i0 = max(0, int((x - radius - self.origin_x) / self.cell))
        i1 = min(self.nx - 1, int((x + radius - self.origin_x) / self.cell))
        j0 = max(0, int((z - radius - self.origin_z) / self.cell))
        j1 = min(self.nz - 1, int((z + radius - self.origin_z) / self.cell))
        for j in range(j0, j1 + 1):
            cz = self.origin_z + (j + 0.5) * self.cell
            for i in range(i0, i1 + 1):
                yield j * self.nx + i, self.origin_x + (i + 0.5) * self.cell, cz

    def _accumulate_zone_inventory(self, index, delta_volume):
        code = self.zone_code[index]
        if code == _ZONE_YARD:
            self.in_zone_m3 += delta_volume
        elif code == _ZONE_SPILL:
            self.spilled_m3 += delta_volume

    def deposit(self, x, z, volume):
        """Place volume through a truncated Gaussian falling-core kernel.

        Only cells inside the spill zone can receive coal; the part of the
        kernel that would land outside it is refused and not counted as input.
        """
        self._require_scene()
        x, z, volume = finite(x), finite(z), finite(volume)
        if volume <= 0:
            raise MotionError("INVALID_COMMAND", "卸料体积必须为正数", 422)
        self._require_in_domain(x, z)
        sigma = self.coal["deposit_sigma_m"]
        radius = 3.0 * sigma
        cells, weights = [], []
        total_weight = 0.0
        for index, cx, cz in self._window_cells(x, z, radius):
            if self.zone_code[index] == _ZONE_OUTSIDE:
                continue
            weight = math.exp(-((cx - x) ** 2 + (cz - z) ** 2) / (2 * sigma * sigma))
            if weight <= 0:
                continue
            cells.append(index)
            weights.append(weight)
            total_weight += weight
        accepted = 0.0
        if total_weight > 0:
            limit = self.coal["max_height"]
            for index, weight in zip(cells, weights):
                share = volume * weight / total_weight
                desired_height = share / self.cell_area
                room = max(0.0, limit - self.heights[index])
                added_height = min(desired_height, room)
                delta = added_height * self.cell_area
                if delta > 0:
                    self.heights[index] += added_height
                    self._accumulate_zone_inventory(index, delta)
                    accepted += delta
        self.ledger["received_m3"] += accepted
        self.version += 1
        reason = None
        if accepted < volume - 1e-9:
            reason = "RECEIVE_LIMITED"
        return dict(requested_m3=volume, accepted_m3=accepted, reason=reason)

    def remove(self, x, z, radius, volume):
        """Withdraw up to volume from the cells whose centres lie in the circle."""
        self._require_scene()
        x, z, radius, volume = finite(x), finite(z), finite(radius), finite(volume)
        if radius <= 0 or volume < 0:
            raise MotionError("INVALID_COMMAND", "取料半径或体积无效", 422)
        self._require_in_domain(x, z)
        cells, available = [], 0.0
        for index, cx, cz in self._window_cells(x, z, radius):
            if (cx - x) ** 2 + (cz - z) ** 2 <= radius * radius and self.heights[index] > 0:
                cells.append(index)
                available += self.heights[index] * self.cell_area
        actual = min(volume, available)
        if available > 0 and actual > 0:
            scale = 1.0 - actual / available
            for index in cells:
                delta = self.heights[index] * self.cell_area
                self.heights[index] *= scale
                delta -= self.heights[index] * self.cell_area
                self._accumulate_zone_inventory(index, -delta)
        self.ledger["output_m3"] += actual
        self.version += 1
        return actual

    def state(self):
        density = self.coal["density_t_per_m3"]
        in_zone, spilled = self.in_zone_m3, self.spilled_m3
        return dict(scene=self.scene, version=self.version,
                    ledger=dict(self.ledger),
                    inventory=dict(in_zone_m3=in_zone, spilled_m3=spilled, total_m3=in_zone + spilled,
                                   in_zone_t=in_zone * density, spilled_t=spilled * density,
                                   total_t=(in_zone + spilled) * density))
