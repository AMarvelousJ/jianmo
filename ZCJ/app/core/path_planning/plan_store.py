from __future__ import annotations

import threading
import time
from collections import OrderedDict

from app.core.path_planning.errors import PathPlanningError
from app.models.path_planning import PathPlan


class PathPlanStore:
    def __init__(self, max_items: int = 100, ttl_seconds: float = 600.0) -> None:
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._plans: OrderedDict[str, tuple[float, PathPlan]] = OrderedDict()
        self._lock = threading.RLock()

    def put(self, plan: PathPlan) -> PathPlan:
        with self._lock:
            self._purge_expired()
            self._plans[plan.plan_id] = (time.monotonic(), plan)
            self._plans.move_to_end(plan.plan_id)
            while len(self._plans) > self.max_items:
                self._plans.popitem(last=False)
            return plan

    def get(self, plan_id: str) -> PathPlan:
        with self._lock:
            item = self._plans.get(plan_id)
            if item is None:
                raise PathPlanningError(
                    "PLAN_NOT_FOUND",
                    f"未找到路径计划 {plan_id}。",
                    status_code=404,
                    context={"plan_id": plan_id},
                )
            created_monotonic, plan = item
            if time.monotonic() - created_monotonic > self.ttl_seconds:
                del self._plans[plan_id]
                raise PathPlanningError(
                    "PLAN_EXPIRED",
                    "路径计划已过期，请重新预览。",
                    status_code=409,
                    context={"plan_id": plan_id},
                )
            self._plans.move_to_end(plan_id)
            return plan

    def clear(self) -> None:
        with self._lock:
            self._plans.clear()

    def _purge_expired(self) -> None:
        now = time.monotonic()
        expired = [
            plan_id
            for plan_id, (created, _) in self._plans.items()
            if now - created > self.ttl_seconds
        ]
        for plan_id in expired:
            del self._plans[plan_id]
