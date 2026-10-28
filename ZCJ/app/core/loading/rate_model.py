from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR


class LoadingRateModel:
    def __init__(self) -> None:
        self._carry_kg: dict[tuple[str, int], Decimal] = {}

    def increment_kg(
        self,
        *,
        task_id: str,
        batch_no: int,
        rate_tph: float,
        loading_scale: float,
        base_dt: float,
        remaining_kg: int,
    ) -> int:
        if base_dt <= 0 or remaining_kg <= 0:
            return 0
        key = (task_id, batch_no)
        carry = self._carry_kg.get(key, Decimal("0"))
        exact = (
            Decimal(str(rate_tph))
            * Decimal("1000")
            * Decimal(str(loading_scale))
            * Decimal(str(base_dt))
            / Decimal("3600")
            + carry
        )
        whole = int(exact.to_integral_value(rounding=ROUND_FLOOR))
        self._carry_kg[key] = exact - Decimal(whole)
        applied = min(remaining_kg, whole)
        if applied >= remaining_kg:
            self._carry_kg.pop(key, None)
        return applied

    def clear_task(self, task_id: str) -> None:
        for key in [key for key in self._carry_kg if key[0] == task_id]:
            self._carry_kg.pop(key, None)
