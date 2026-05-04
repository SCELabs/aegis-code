from __future__ import annotations

import threading
from typing import Any


def _call_with_timeout(fn: Any, timeout_ms: int) -> tuple[bool, Any]:
    holder: dict[str, Any] = {"result": None, "error": None}

    def _run() -> None:
        try:
            holder["result"] = fn()
        except Exception as exc:
            holder["error"] = exc

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=max(0.001, float(timeout_ms) / 1000.0))
    if thread.is_alive():
        return False, TimeoutError(f"aegis advisory timeout after {int(timeout_ms)}ms")
    if holder["error"] is not None:
        return False, holder["error"]
    return True, holder["result"]


def get_aegis_guidance(
    *,
    task: str,
    context: dict,
    failures: dict,
    runtime_policy: dict,
    timeout_ms: int,
    max_retries: int,
) -> dict:
    try:
        _ = failures
        advisory_enabled = bool((context or {}).get("aegis", {}).get("enabled", False))
        if not advisory_enabled:
            return {"available": False}

        try:
            from aegis import AegisClient, AegisConfig  # type: ignore
        except Exception:
            return {"available": False}

        selected_mode = str((runtime_policy or {}).get("selected_mode", "balanced") or "balanced")
        retries = max(0, int(max_retries))
        timeout_value = max(1, int(timeout_ms))
        last_error: Exception | None = None

        for _attempt in range(retries + 1):
            client = AegisClient(config=AegisConfig(mode=selected_mode))
            ok, value = _call_with_timeout(
                lambda: client.auto().llm(
                    input=str(task or ""),
                    context=context,
                ),
                timeout_value,
            )
            if ok:
                result = value
                actions = getattr(result, "actions", None)
                explanation = getattr(result, "explanation", "")
                used_fallback = getattr(result, "used_fallback", False)
                return {
                    "available": True,
                    "actions": actions if isinstance(actions, list) else [],
                    "explanation": str(explanation or ""),
                    "used_fallback": bool(used_fallback),
                }
            last_error = value if isinstance(value, Exception) else Exception(str(value))

        return {"available": False, "error": str(last_error or "aegis_advisory_unavailable")}
    except Exception as exc:
        return {"available": False, "error": str(exc)}
