from __future__ import annotations

import math

import numpy as np

from app.core.path_planning.errors import PathPlanningError
from app.models.path_planning import (
    GridCell,
    GridTargetRequest,
    HoldGridResponse,
    PathTarget,
)
from app.models.pose import Vec3
from app.models.scene import HoldConfig, SceneConfig, VesselConfig
from app.utils.math_utils import rotation_z


def normalize_angle(angle_deg: float) -> float:
    normalized = (angle_deg + 180.0) % 360.0 - 180.0
    return 180.0 if math.isclose(normalized, -180.0) and angle_deg > 0 else normalized


class GridTransformer:
    def find_vessel_hold(
        self,
        scene: SceneConfig,
        vessel_id: str,
        hold_id: str,
    ) -> tuple[VesselConfig, HoldConfig]:
        vessel = next((item for item in scene.vessels if item.id == vessel_id), None)
        if vessel is None:
            raise PathPlanningError(
                "VESSEL_NOT_FOUND",
                f"未找到船舶 {vessel_id}。",
                status_code=404,
                context={"vessel_id": vessel_id},
            )
        hold = next((item for item in vessel.holds if item.id == hold_id), None)
        if hold is None:
            raise PathPlanningError(
                "HOLD_NOT_FOUND",
                f"船舶 {vessel_id} 中未找到舱口 {hold_id}。",
                status_code=404,
                context={"vessel_id": vessel_id, "hold_id": hold_id},
            )
        return vessel, hold

    def grid_response(
        self,
        scene: SceneConfig,
        vessel_id: str,
        hold_id: str,
    ) -> HoldGridResponse:
        vessel, hold = self.find_vessel_hold(scene, vessel_id, hold_id)
        self._require_hatch_height(hold)
        cell_length = hold.length_m / hold.grid.columns
        cell_width = hold.width_m / hold.grid.rows
        cells: list[GridCell] = []
        for column in range(1, hold.grid.columns + 1):
            for row in range(1, hold.grid.rows + 1):
                cell_x, cell_y = self._cell_local(hold, column, row)
                world = self._world_point(
                    vessel,
                    hold,
                    cell_x,
                    cell_y,
                    loading_clearance_m=0.0,
                )
                cells.append(
                    GridCell(
                        column=column,
                        row=row,
                        local_center_m=Vec3(x=cell_x, y=cell_y, z=0.0),
                        world_center_m=Vec3.from_array(world),
                    )
                )
        return HoldGridResponse(
            vessel_id=vessel.id,
            hold_id=hold.id,
            scene_revision=scene.revision,
            columns=hold.grid.columns,
            rows=hold.grid.rows,
            index_base=hold.grid.index_base,
            column_direction=hold.grid.column_direction,
            row_direction=hold.grid.row_direction,
            cell_length_m=cell_length,
            cell_width_m=cell_width,
            cells=cells,
        )

    def target(self, scene: SceneConfig, request: GridTargetRequest) -> PathTarget:
        vessel, hold = self.find_vessel_hold(scene, request.vessel_id, request.hold_id)
        self._validate_grid(hold, request.column, request.row)
        self._require_hatch_height(hold)
        self._require_cover_open(hold)
        if not math.isclose(request.loading_clearance_m, 1.0, abs_tol=1e-9):
            raise PathPlanningError(
                "LOADING_CLEARANCE_UNSUPPORTED",
                "P0 装料净空固定为 1.0 m。",
                context={"requested": request.loading_clearance_m, "supported": 1.0},
            )
        cell_x, cell_y = self._cell_local(hold, request.column, request.row)
        world = self._world_point(
            vessel,
            hold,
            cell_x,
            cell_y,
            loading_clearance_m=request.loading_clearance_m,
        )
        heading = normalize_angle(
            vessel.yaw_deg if request.chute_heading_deg is None else request.chute_heading_deg
        )
        return PathTarget(
            vessel_id=vessel.id,
            hold_id=hold.id,
            column=request.column,
            row=request.row,
            hold_local_point=Vec3(
                x=cell_x,
                y=cell_y,
                z=request.loading_clearance_m,
            ),
            world_point=Vec3.from_array(world),
            heading_deg=heading,
            loading_clearance_m=request.loading_clearance_m,
        )

    def require_target_config_open(
        self,
        scene: SceneConfig,
        vessel_id: str,
        hold_id: str,
    ) -> tuple[VesselConfig, HoldConfig]:
        vessel, hold = self.find_vessel_hold(scene, vessel_id, hold_id)
        self._require_hatch_height(hold)
        self._require_cover_open(hold)
        return vessel, hold

    @staticmethod
    def _cell_local(hold: HoldConfig, column: int, row: int) -> tuple[float, float]:
        cell_length = hold.length_m / hold.grid.columns
        cell_width = hold.width_m / hold.grid.rows
        return (
            -hold.length_m / 2.0 + (column - 0.5) * cell_length,
            -hold.width_m / 2.0 + (row - 0.5) * cell_width,
        )

    @staticmethod
    def _world_point(
        vessel: VesselConfig,
        hold: HoldConfig,
        cell_x: float,
        cell_y: float,
        *,
        loading_clearance_m: float,
    ) -> np.ndarray:
        local = np.array(
            [
                hold.center_offset_m + cell_x,
                cell_y,
                hold.hatch_plane_offset_z_m + loading_clearance_m,
            ],
            dtype=float,
        )
        rotated = rotation_z(vessel.yaw_deg) @ local
        return vessel.position.to_array() + rotated

    @staticmethod
    def _validate_grid(hold: HoldConfig, column: int, row: int) -> None:
        if not 1 <= column <= hold.grid.columns:
            raise PathPlanningError(
                "GRID_OUT_OF_RANGE",
                f"列号必须在 1～{hold.grid.columns} 之间。",
                context={"field": "column", "value": column, "min": 1, "max": hold.grid.columns},
            )
        if not 1 <= row <= hold.grid.rows:
            raise PathPlanningError(
                "GRID_OUT_OF_RANGE",
                f"行号必须在 1～{hold.grid.rows} 之间。",
                context={"field": "row", "value": row, "min": 1, "max": hold.grid.rows},
            )

    @staticmethod
    def _require_hatch_height(hold: HoldConfig) -> None:
        if hold.hatch_plane_offset_z_m is None:
            raise PathPlanningError(
                "HATCH_HEIGHT_MISSING",
                f"舱口 {hold.id} 缺少 hatch_plane_offset_z_m。",
                context={"hold_id": hold.id},
            )

    @staticmethod
    def _require_cover_open(hold: HoldConfig) -> None:
        if hold.cover_state is None:
            raise PathPlanningError(
                "HATCH_COVER_STATE_MISSING",
                f"舱口 {hold.id} 缺少 cover_state。",
                context={"hold_id": hold.id},
            )
        if hold.cover_state != "open":
            raise PathPlanningError(
                "HATCH_COVER_CLOSED",
                f"舱口 {hold.id} 的舱盖未打开。",
                context={"hold_id": hold.id, "cover_state": hold.cover_state},
            )
