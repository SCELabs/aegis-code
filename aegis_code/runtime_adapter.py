from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.aegis_client import AegisBackendClient
from aegis_code.config import load_config

if TYPE_CHECKING:
    from aegis_code.runtime import TaskOptions


def _normalize_client_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "output": raw.get("output"),
            "final_answer": raw.get("final_answer"),
            "metrics": raw.get("metrics", {}),
            "actions": raw.get("actions", []),
            "trace": raw.get("trace", []),
            "explanation": raw.get("explanation", ""),
        }
    return {
        "output": None,
        "final_answer": str(raw) if raw is not None else "",
        "metrics": {},
        "actions": [],
        "trace": [],
        "explanation": "",
    }


def execute_task(
    task_options: "TaskOptions",
    *,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    from aegis_code.runtime import _run_task_local

    cfg = load_config(cwd)
    enhanced_enabled = bool(cfg.aegis.enhanced_runtime)
    aegis_available = False
    adapter_mode = "local"
    fallback_reason = "disabled"

    try:
        from aegis import AegisClient  # type: ignore

        _ = AegisClient
        aegis_available = True
    except Exception:
        aegis_available = False
        fallback_reason = "import_missing"

    if enhanced_enabled and aegis_available:
        try:
            aegis_client = AegisClient()
            raw_result = aegis_client.auto().llm(
                prompt=task_options.task,
                context=task_options.project_context or {},
                metadata={
                    "budget": task_options.budget_state or {},
                    "policy": task_options.runtime_policy or {},
                },
            )
            result = _run_task_local(options=task_options, cwd=cwd, client=client)
            result.update(_normalize_client_result(raw_result))
            adapter_mode = "aegis"
            fallback_reason = None
        except Exception:
            result = _run_task_local(options=task_options, cwd=cwd, client=client)
            adapter_mode = "local"
            fallback_reason = "client_error"
    else:
        result = _run_task_local(options=task_options, cwd=cwd, client=client)
        adapter_mode = "local"
        fallback_reason = "disabled" if not enhanced_enabled else "import_missing"

    result["adapter"] = {
        "mode": adapter_mode,
        "aegis_client_available": aegis_available,
        "enhanced_enabled": enhanced_enabled,
        "fallback_reason": fallback_reason,
    }
    return result
