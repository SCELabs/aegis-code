from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BudgetState:
    total: float
    spent: float = 0.0

    @property
    def remaining(self) -> float:
        return max(0.0, float(self.total) - float(self.spent))

    def to_dict(self) -> dict[str, float]:
        return {
            "total": float(self.total),
            "spent": float(self.spent),
            "remaining": float(self.remaining),
        }


def _budget_path(cwd: Path | None = None) -> Path:
    root = cwd or Path.cwd()
    return root / ".aegis" / "budget.json"


def load_budget(cwd: Path | None = None) -> dict[str, Any] | None:
    path = _budget_path(cwd)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return None
    return data


def save_budget(data: dict[str, Any], cwd: Path | None = None) -> None:
    path = _budget_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_budget(limit: float, cwd: Path | None = None) -> dict[str, Any]:
    data = {
        "limit": float(limit),
        "spent_estimate": 0.0,
        "currency": "USD",
        "events": [],
    }
    save_budget(data, cwd)
    return data


def clear_budget(cwd: Path | None = None) -> None:
    path = _budget_path(cwd)
    if path.exists():
        path.unlink()


def can_spend(operation: str, estimated_cost: float, cwd: Path | None = None) -> bool:
    _ = operation
    data = load_budget(cwd)
    if not data:
        return True
    limit = float(data.get("limit", 0.0) or 0.0)
    spent = float(data.get("spent_estimate", 0.0) or 0.0)
    return spent + float(estimated_cost) <= limit


def record_event(operation: str, estimated_cost: float, cwd: Path | None = None) -> dict[str, Any] | None:
    data = load_budget(cwd)
    if not data:
        return None
    spent = float(data.get("spent_estimate", 0.0) or 0.0) + float(estimated_cost)
    events = list(data.get("events", []))
    events.append({"operation": operation, "estimated_cost": float(estimated_cost)})
    data["spent_estimate"] = spent
    data["events"] = events
    save_budget(data, cwd)
    return data
