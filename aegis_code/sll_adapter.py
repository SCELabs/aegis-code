from __future__ import annotations

import importlib
from typing import Any


SLL_IMPORT_PATH = "structural_language_lab"


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _unavailable() -> dict[str, Any]:
    return {"available": False}


def _load_analyze_sequence() -> tuple[Any | None, str | None]:
    try:
        module = importlib.import_module(SLL_IMPORT_PATH)
    except Exception as exc:
        return None, str(exc)
    analyze_sequence = getattr(module, "analyze_sequence", None)
    if analyze_sequence is None:
        return None, f"Cannot import name 'analyze_sequence' from '{SLL_IMPORT_PATH}'"
    return analyze_sequence, None


def check_sll_available() -> dict[str, Any]:
    analyze_sequence, error = _load_analyze_sequence()
    return {
        "available": analyze_sequence is not None,
        "import_path": SLL_IMPORT_PATH,
        "error": error,
    }


def analyze_failures_sll(failure_text: str) -> dict[str, Any]:
    if not failure_text.strip():
        return _unavailable()

    analyze_sequence, _error = _load_analyze_sequence()
    if analyze_sequence is None:
        return _unavailable()

    try:
        assert analyze_sequence is not None
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


def run_sll_analysis(text: str) -> dict[str, Any]:
    if not str(text or "").strip():
        return _unavailable()

    analyze_sequence, _error = _load_analyze_sequence()
    if analyze_sequence is None:
        return _unavailable()

    try:
        result = analyze_sequence(text)
    except Exception:
        return _unavailable()

    payload: dict[str, Any]
    if isinstance(result, dict):
        payload = result
    else:
        payload = {
            "regime": getattr(result, "regime", "unknown"),
            "coherence": getattr(result, "coherence", None),
            "collapse_risk": getattr(result, "collapse_risk", None),
            "fragmentation_risk": getattr(result, "fragmentation_risk", None),
            "drift_risk": getattr(result, "drift_risk", None),
            "recommendation": getattr(result, "recommendation", None),
        }

    regime = str(payload.get("regime", "unknown") or "unknown").strip().lower()
    if regime not in {"unity", "boundary", "fragmentation"}:
        regime = "unknown"

    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    recommendation = payload.get("recommendation")
    return {
        "available": True,
        "regime": regime,
        "coherence": _optional_float(payload.get("coherence")),
        "collapse_risk": _optional_float(payload.get("collapse_risk")),
        "fragmentation_risk": _optional_float(payload.get("fragmentation_risk")),
        "drift_risk": _optional_float(payload.get("drift_risk")),
        "recommendation": str(recommendation) if recommendation is not None else None,
    }


def classify_sll_risk(sll_data: dict[str, Any]) -> str:
    if not isinstance(sll_data, dict) or not bool(sll_data.get("available", False)):
        return "low"
    collapse = sll_data.get("collapse_risk")
    fragmentation = sll_data.get("fragmentation_risk")
    drift = sll_data.get("drift_risk")
    risks = [value for value in (collapse, fragmentation, drift) if isinstance(value, (int, float))]
    if not risks:
        return "low"
    if (isinstance(collapse, (int, float)) and float(collapse) > 0.7) or (
        isinstance(fragmentation, (int, float)) and float(fragmentation) > 0.7
    ):
        return "high"
    if any(float(value) > 0.4 for value in risks):
        return "watch"
    return "low"
