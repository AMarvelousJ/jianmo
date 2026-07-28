from __future__ import annotations

from app.core.path_planning.errors import PathPlanningError
from app.core.path_planning.path_planner import PathPlanner
from app.core.scene_state import SceneState
from app.models.loading import (
    LoadingPathCheck,
    LoadingPlan,
    LoadingPlanValidation,
    LoadingValidationIssue,
)
from app.models.path_planning import GridTargetRequest


class LoadingPlanValidator:
    EXPECTED_HOLD_MAPPING = {
        "No.1": "R1",
        "No.2": "R2",
        "No.3": "R3",
        "No.4": "R4",
        "No.5": "R5",
    }

    def __init__(
        self,
        scene_state: SceneState,
        path_planner: PathPlanner,
    ) -> None:
        self.scene_state = scene_state
        self.path_planner = path_planner

    def validate(self, plan: LoadingPlan, *, check_paths: bool = True) -> LoadingPlanValidation:
        scene = self.scene_state.get_scene()
        errors: list[LoadingValidationIssue] = []
        warnings: list[LoadingValidationIssue] = []
        path_checks: list[LoadingPathCheck] = []
        batches = plan.batches()
        round_totals = {
            round_.round_no: sum(batch.target_kg for batch in round_.batches)
            for round_ in plan.rounds
        }
        hold_totals = {
            hold_no: sum(
                batch.target_kg
                for batch in batches
                if batch.hold_no == hold_no
            )
            for hold_no in plan.hold_mapping
        }
        calculated_total = sum(batch.target_kg for batch in batches)

        self._expect(
            [round_.round_no for round_ in plan.rounds] == [1, 2, 3],
            errors,
            "ROUND_SEQUENCE_INVALID",
            "轮次必须严格为 1、2、3。",
        )
        self._expect(
            [batch.batch_no for batch in batches] == list(range(1, 13)),
            errors,
            "BATCH_SEQUENCE_INVALID",
            "全局批次必须严格为 1～12。",
        )
        self._expect(
            calculated_total == plan.total_target_kg,
            errors,
            "PLAN_TOTAL_MISMATCH",
            "批次合计与整船目标不一致。",
            {"expected": plan.total_target_kg, "actual": calculated_total},
        )
        for round_ in plan.rounds:
            self._expect(
                round_totals.get(round_.round_no) == round_.target_kg,
                errors,
                "ROUND_TOTAL_MISMATCH",
                f"第 {round_.round_no} 轮吨位合计不一致。",
                {
                    "round_no": round_.round_no,
                    "expected": round_.target_kg,
                    "actual": round_totals.get(round_.round_no),
                },
            )
        self._expect(
            plan.hold_mapping == self.EXPECTED_HOLD_MAPPING,
            errors,
            "HOLD_MAPPING_INVALID",
            "P0 舱号映射必须为 No.1～No.5 对应 R1～R5。",
            {"actual": plan.hold_mapping},
        )
        self._expect(
            sum(hold_totals.values()) == plan.total_target_kg,
            errors,
            "HOLD_TOTAL_MISMATCH",
            "分舱合计与整船目标不一致。",
        )

        vessel = next(
            (item for item in scene.vessels if item.id == plan.vessel_id),
            None,
        )
        self._expect(
            vessel is not None,
            errors,
            "LOADING_VESSEL_NOT_FOUND",
            f"场景中不存在目标船舶 {plan.vessel_id}。",
        )
        if vessel is not None:
            holds = {hold.id: hold for hold in vessel.holds}
            for hold_no, hold_id in plan.hold_mapping.items():
                hold = holds.get(hold_id)
                self._expect(
                    hold is not None,
                    errors,
                    "LOADING_HOLD_NOT_FOUND",
                    f"场景中不存在货舱 {hold_id}。",
                    {"hold_no": hold_no, "hold_id": hold_id},
                )
                if hold is not None:
                    self._expect(
                        hold.cover_state == "open",
                        errors,
                        "HATCH_COVER_CLOSED",
                        f"货舱 {hold_id} 舱盖未打开。",
                        {"hold_id": hold_id},
                    )

        if check_paths and not errors:
            for batch in batches:
                try:
                    preview = self.path_planner.preview(
                        GridTargetRequest(
                            vessel_id=plan.vessel_id,
                            hold_id=batch.hold_id,
                            column=batch.column,
                            row=batch.row,
                        )
                    )
                    path_checks.append(
                        LoadingPathCheck(
                            batch_no=batch.batch_no,
                            hold_id=batch.hold_id,
                            column=batch.column,
                            row=batch.row,
                            feasible=True,
                            estimated_duration_s=preview.estimated_duration_s,
                        )
                    )
                except PathPlanningError as error:
                    errors.append(
                        LoadingValidationIssue(
                            code=error.code,
                            message=error.message,
                            context={"batch_no": batch.batch_no, **error.context},
                        )
                    )
                    path_checks.append(
                        LoadingPathCheck(
                            batch_no=batch.batch_no,
                            hold_id=batch.hold_id,
                            column=batch.column,
                            row=batch.row,
                            feasible=False,
                            error_code=error.code,
                            message=error.message,
                        )
                    )

        current_revision = self.scene_state.get_scene().revision
        self._expect(
            current_revision == scene.revision,
            errors,
            "SCENE_REVISION_MISMATCH",
            "配载计划校验期间场景版本发生变化。",
            {
                "validation_revision": scene.revision,
                "current_revision": current_revision,
            },
        )

        return LoadingPlanValidation(
            valid=not errors,
            scene_revision=scene.revision,
            calculated_total_kg=calculated_total,
            round_totals_kg=round_totals,
            hold_totals_kg=hold_totals,
            errors=errors,
            warnings=warnings,
            path_checks=path_checks,
        )

    @staticmethod
    def _expect(
        condition: bool,
        errors: list[LoadingValidationIssue],
        code: str,
        message: str,
        context: dict[str, object] | None = None,
    ) -> None:
        if not condition:
            errors.append(
                LoadingValidationIssue(
                    code=code,
                    message=message,
                    context=context or {},
                )
            )
