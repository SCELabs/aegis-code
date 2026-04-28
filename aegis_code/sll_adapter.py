from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def analyze_failures_sll(failure_text: str) -> dict[str, Any] | None:
    if not failure_text.strip():
        return None

    try:
        from structural_language_lab import analyze_sequence
    except Exception:
        return None

    try:
        result = analyze_sequence(failure_text)
    except Exception:
        return None

    if isinstance(result, dict):
        payload = result
    else:
        payload = {
            "regime": getattr(result, "regime", "unknown"),
            "collapse_risk": getattr(result, "collapse_risk", 0.0),
            "fragmentation_risk": getattr(result, "fragmentation_risk", 0.0),
            "drift_risk": getattr(result, "drift_risk", 0.0),
        }

    return {
        "regime": str(payload.get("regime", "unknown")),
        "collapse_risk": _as_float(payload.get("collapse_risk", 0.0)),
        "fragmentation_risk": _as_float(payload.get("fragmentation_risk", 0.0)),
        "drift_risk": _as_float(payload.get("drift_risk", 0.0)),
    }

