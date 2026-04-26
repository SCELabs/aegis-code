from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class BudgetState:
    total: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return max(self.total - self.spent, 0.0)

    def to_dict(self) -> dict[str, float]:
        return {
            "total": round(self.total, 4),
            "spent": round(self.spent, 4),
            "remaining": round(self.remaining, 4),
        }
