from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.aegis_client import AegisBackendClient
from aegis_code.config import load_config
from aegis_code.report import write_reports

if TYPE_CHECKING:
    from aegis_code.runtime import TaskOptions


def _to_mapping(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if is_dataclass(raw):
        return asdict(raw)
    if hasattr(raw, "__dict__"):
        return dict(raw.__dict__)
    return {}


def _normalize_aegis_result(raw: Any) -> dict[str, Any]:
    data = _to_mapping(raw)
    if data:
        normalized: dict[str, Any] = {}
        for key in (
            "output",
            "final_answer",
            "metrics",
            "actions",
            "trace",
            "explanation",
            "guidance",
            "note",
            "execution",
        ):
            if key in data:
                normalized[key] = data[key]
        return normalized
    if raw is None:
        return {}
    return {"explanation": str(raw)}


def _short_error_message(exc: Exception, max_chars: int = 300) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    return text if len(text) <= max_chars else (text[: max_chars - 3] + "...")


def _apply_context_mode(project_context: dict[str, Any] | None, mode: str | None) -> dict[str, Any] | None:
    if not isinstance(project_context, dict):
        return project_context
    context = dict(project_context)
    selected = str(mode or "").strip().lower()
    if selected not in {"minimal", "balanced", "full"}:
        return context
    if selected == "balanced":
        return context
    if selected == "full":
        return context

    # minimal: deterministically reduce context content budget by half
    files = context.get("files")
    if isinstance(files, dict):
        reduced: dict[str, Any] = {}
        for key, value in files.items():
            text = str(value)
            reduced[key] = text[: max(1, len(text) // 2)]
        context["files"] = reduced
    total_chars = context.get("total_chars")
    if isinstance(total_chars, int):
        context["total_chars"] = max(0, total_chars // 2)
    return context


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
    response: Any = None
    error_type: str | None = None
    error_message: str | None = None
    guidance: dict[str, Any] = {}

    try:
        from aegis import AegisClient  # type: ignore

        _ = AegisClient
        aegis_available = True
    except Exception:
        aegis_available = False
        fallback_reason = "import_missing"

    if not enhanced_enabled:
        fallback_reason = "disabled"

    if enhanced_enabled and aegis_available:
        try:
            aegis_client = AegisClient(base_url=cfg.aegis.base_url)
            response = aegis_client.auto().step(
                step_name="aegis-code-runtime",
                step_input={
                    "task": task_options.task,
                    "mode": task_options.mode,
                    "dry_run": task_options.dry_run,
                },
                symptoms=["unstable_workflow"],
                severity="medium",
                metadata={
                    "project_context": task_options.project_context or {},
                    "budget_state": task_options.budget_state or {},
                    "runtime_policy": task_options.runtime_policy or {},
                    "verification": None,
                    "failures": None,
                    "status": None,
                },
            )
            response_map = _to_mapping(response)
            guidance = {
                "model_tier": response_map.get("model_tier"),
                "max_retries": response_map.get("max_retries"),
                "allow_escalation": response_map.get("allow_escalation"),
                "context_mode": response_map.get("context_mode"),
            }
            adapter_mode = "aegis"
            fallback_reason = None
        except Exception as exc:
            response = None
            adapter_mode = "local"
            fallback_reason = "client_error"
            error_type = exc.__class__.__name__
            error_message = _short_error_message(exc)

    local_options = task_options
    if guidance:
        from aegis_code.runtime import TaskOptions

        local_options = TaskOptions(
            task=task_options.task,
            budget=task_options.budget,
            mode=task_options.mode,
            dry_run=task_options.dry_run,
            analyze_failures=task_options.analyze_failures,
            propose_patch=task_options.propose_patch,
            session=task_options.session,
            no_report=task_options.no_report,
            project_context=_apply_context_mode(task_options.project_context, guidance.get("context_mode")),
            budget_state=task_options.budget_state,
            runtime_policy=task_options.runtime_policy,
            aegis_guidance=guidance,
        )

    local_result = _run_task_local(
        options=local_options,
        cwd=cwd,
        client=client,
        write_report=False,
    )

    result = dict(local_result)
    if adapter_mode == "aegis" and response is not None:
        aegis_result = _normalize_aegis_result(response)
        result["aegis_result"] = aegis_result
        result["aegis_guidance"] = guidance
        for key in ("actions", "trace", "explanation", "metrics"):
            value = aegis_result.get(key)
            if value is not None:
                result[key] = value
    result["adapter"] = {
        "mode": adapter_mode,
        "aegis_client_available": aegis_available,
        "enhanced_enabled": enhanced_enabled,
        "fallback_reason": fallback_reason,
        "error_type": error_type,
        "error_message": error_message,
    }
    if not task_options.no_report:
        write_reports(result, cwd=cwd)
    return result
