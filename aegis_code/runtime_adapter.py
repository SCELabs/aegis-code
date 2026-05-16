from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.aegis_client import AegisBackendClient, apply_resolved_aegis_env
from aegis_code.config import load_config
from aegis_code.report import write_reports
from aegis_code.runtime_control_service import RuntimeControlService
from aegis_code.usage import update_usage

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


def _build_aegis_impact(
    *,
    adapter_mode: str,
    fallback_reason: str | None,
    actions: Any,
    guidance: dict[str, Any],
) -> dict[str, Any]:
    fallback_used = bool(fallback_reason)
    used = adapter_mode == "aegis" and not fallback_used
    action_count = len(actions) if isinstance(actions, list) else 0
    guidance_applied = any(value is not None for value in guidance.values())
    override_applied = bool(used and (guidance_applied or action_count > 0))
    return {
        "used": used,
        "action_count": action_count,
        "override_applied": override_applied,
        "fallback_used": fallback_used,
        "reason": fallback_reason if not used else "guidance_applied",
    }


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


def _resolve_legacy_aegis_guidance(
    *,
    control_guidance: dict[str, Any] | None,
    advisory_guidance: dict[str, Any] | None,
    legacy_guidance: Any = None,
) -> dict[str, Any] | None:
    if isinstance(advisory_guidance, dict) and advisory_guidance:
        return advisory_guidance
    if isinstance(control_guidance, dict) and control_guidance:
        return control_guidance
    if isinstance(legacy_guidance, dict):
        return legacy_guidance
    return None


def execute_task(
    task_options: "TaskOptions",
    *,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    from aegis_code.runtime import _run_task_local

    cfg = load_config(cwd)
    resolved_cwd = (cwd or Path.cwd()).resolve()
    apply_resolved_aegis_env(resolved_cwd, default_base_url=cfg.aegis.base_url)
    control_service = RuntimeControlService(
        options=task_options,
        config=cfg,
        cwd=resolved_cwd,
    )
    control_state = control_service.control_state
    control_requested = bool(control_state.get("requested", False))

    adapter_mode = "local"
    fallback_reason = "disabled_by_config"
    response: Any = None
    error_type: str | None = None
    error_message: str | None = None
    guidance: dict[str, Any] = {}
    aegis_available = control_service.is_client_available()

    if not control_requested:
        reason = str(control_state.get("reason", "disabled_by_config") or "disabled_by_config")
        if reason == "no_api_key":
            fallback_reason = "no_api_key"
        else:
            fallback_reason = "disabled_by_config"
    step_result = control_service.get_step_guidance(
        task=task_options.task,
        payload={
            "mode": task_options.mode,
            "dry_run": task_options.dry_run,
            "project_context": task_options.project_context or {},
            "budget_state": task_options.budget_state or {},
            "runtime_policy": task_options.runtime_policy or {},
            "verification": None,
            "failures": None,
            "status": None,
        },
    )
    step_status = str(step_result.get("status", "disabled") or "disabled")
    step_reason = str(step_result.get("reason", "disabled_by_config") or "disabled_by_config")
    response = step_result.get("response")
    guidance = step_result.get("guidance", {}) if isinstance(step_result.get("guidance", {}), dict) else {}
    step_error = step_result.get("error")
    step_error_type = step_result.get("error_type")

    if step_status == "applied":
        aegis_available = True
        adapter_mode = "aegis"
        fallback_reason = None
    elif step_status == "not_available":
        aegis_available = False
        fallback_reason = "import_missing"
    elif step_status == "client_error":
        aegis_available = True
        adapter_mode = "local"
        fallback_reason = "client_error"
        if isinstance(step_error_type, str) and step_error_type.strip():
            error_type = step_error_type.strip()
        if isinstance(step_error, str):
            error_message = _short_error_message(RuntimeError(step_error))
    elif step_status == "disabled":
        if step_reason == "no_api_key":
            fallback_reason = "no_api_key"
        else:
            fallback_reason = "disabled_by_config"

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
            progress_callback=task_options.progress_callback,
            provider_timeout_seconds=task_options.provider_timeout_seconds,
            command=task_options.command,
            scope_contract=task_options.scope_contract,
        )

    local_result = _run_task_local(
        options=local_options,
        cwd=cwd,
        client=client,
        write_report=False,
    )

    result = dict(local_result)
    advisory_guidance = result.get("advisory_guidance")
    if not isinstance(advisory_guidance, dict):
        advisory_guidance = None
    existing_legacy_guidance = result.get("aegis_guidance")
    existing_control_guidance = result.get("control_guidance")
    if not isinstance(existing_control_guidance, dict):
        existing_control_guidance = None
    control_guidance = guidance if guidance else existing_control_guidance
    if adapter_mode == "aegis" and response is not None:
        aegis_result = _normalize_aegis_result(response)
        result["aegis_result"] = aegis_result
        for key in ("actions", "trace", "explanation", "metrics"):
            value = aegis_result.get(key)
            if value is not None:
                result[key] = value
    result["control_guidance"] = control_guidance
    result["advisory_guidance"] = advisory_guidance
    result["aegis_guidance"] = _resolve_legacy_aegis_guidance(
        control_guidance=control_guidance,
        advisory_guidance=advisory_guidance,
        legacy_guidance=existing_legacy_guidance,
    )
    control_status = "enabled" if adapter_mode == "aegis" else ("fallback" if control_requested else "disabled")
    control_reason = "guidance_applied" if adapter_mode == "aegis" else fallback_reason
    result["adapter"] = {
        "mode": adapter_mode,
        "aegis_client_available": aegis_available,
        "control_requested": bool(control_requested),
        "control_status": control_status,
        "control_reason": control_reason,
        "execution": "local",
        "mutation": "confirm_only",
        "fallback_reason": fallback_reason,
        "error_type": error_type,
        "error_message": error_message,
    }
    result["aegis_impact"] = _build_aegis_impact(
        adapter_mode=adapter_mode,
        fallback_reason=fallback_reason,
        actions=result.get("actions"),
        guidance=guidance,
    )
    update_usage(
        {
            **result["aegis_impact"],
            "client_available": aegis_available,
        },
        cwd=(cwd or Path.cwd()).resolve(),
    )
    if not task_options.no_report:
        callback = getattr(task_options, "progress_callback", None)
        if callable(callback):
            try:
                callback("writing report")
            except Exception:
                pass
        write_reports(result, cwd=cwd)
    return result
