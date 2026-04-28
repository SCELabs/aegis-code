from __future__ import annotations

from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unavailable() -> dict[str, Any]:
    return {"available": False}


def analyze_failures_sll(failure_text: str) -> dict[str, Any]:
    if not failure_text.strip():
        return _unavailable()

    try:
        from structural_language_lab import analyze_sequence
    except Exception:
        return _unavailable()

    try:
        result = analyze_sequence(failure_text)
    except Exception:
        return _unavailable()

    if isinstance(result, dict):
        payload = result
    else:
        payload = {
            "regime": getattr(result, "regime", "unknown"),
            "collapse_risk": getattr(result, "collapse_risk", 0.0),
            "fragmentation_risk": getattr(result, "fragmentation_risk", 0.0),
            "drift_risk": getattr(result, "drift_risk", 0.0),
            "stable_random_risk": getattr(result, "stable_random_risk", 0.0),
        }

    return {
        "available": True,
        "regime": str(payload.get("regime", "unknown")),
        "collapse_risk": _as_float(payload.get("collapse_risk", 0.0)),
        "fragmentation_risk": _as_float(payload.get("fragmentation_risk", 0.0)),
        "drift_risk": _as_float(payload.get("drift_risk", 0.0)),
        "stable_random_risk": _as_float(payload.get("stable_random_risk", 0.0)),
    }
