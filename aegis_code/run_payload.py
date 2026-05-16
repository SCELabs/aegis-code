from __future__ import annotations

from typing import Any


def _normalize_model_selection(payload: dict[str, Any]) -> dict[str, Any]:
    existing = payload.get("model_selection", {})
    model_selection = dict(existing) if isinstance(existing, dict) else {}

    legacy_model = str(payload.get("selected_model", "") or "").strip()
    provider = str(model_selection.get("provider", "") or "").strip()
    model = str(model_selection.get("model", "") or "").strip()

    if ":" in legacy_model:
        legacy_provider, legacy_model_name = legacy_model.split(":", 1)
    else:
        legacy_provider, legacy_model_name = "", legacy_model

    if not provider:
        provider = legacy_provider or str((payload.get("patch_diff", {}) or {}).get("provider", "") or "").strip()
    if not model:
        model = legacy_model_name or legacy_model

    runtime_policy = payload.get("runtime_policy", {}) if isinstance(payload.get("runtime_policy", {}), dict) else {}
    mode = (
        str(model_selection.get("mode", "") or "").strip()
        or str(runtime_policy.get("selected_mode", "") or "").strip()
        or str(payload.get("mode", "") or "").strip()
        or "balanced"
    )
    reason = (
        str(model_selection.get("reason", "") or "").strip()
        or str(runtime_policy.get("reason", "") or "").strip()
        or "default"
    )
    tier = str(model_selection.get("tier", "") or "").strip() or str(payload.get("selected_model_tier", "") or "").strip() or "mid"

    timeout_value = model_selection.get("provider_timeout_seconds")
    if timeout_value is None:
        timeout_value = payload.get("provider_timeout_seconds")

    normalized = {
        "provider": provider or "unknown",
        "model": model or "unknown",
        "tier": tier,
        "mode": mode,
        "reason": reason,
    }
    if timeout_value is not None:
        normalized["provider_timeout_seconds"] = timeout_value
    return normalized


def _resolve_legacy_aegis_guidance(
    *,
    control_guidance: dict[str, Any] | None,
    advisory_guidance: dict[str, Any] | None,
    legacy_guidance: Any,
) -> dict[str, Any] | None:
    if isinstance(advisory_guidance, dict) and advisory_guidance:
        return advisory_guidance
    if isinstance(control_guidance, dict) and control_guidance:
        return control_guidance
    if isinstance(legacy_guidance, dict):
        return legacy_guidance
    return None


def normalize_run_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault("schema_version", 1)

    control_guidance = normalized.get("control_guidance")
    if not isinstance(control_guidance, dict):
        control_guidance = None
    advisory_guidance = normalized.get("advisory_guidance")
    if not isinstance(advisory_guidance, dict):
        advisory_guidance = None

    normalized["control_guidance"] = control_guidance
    normalized["advisory_guidance"] = advisory_guidance
    normalized["aegis_guidance"] = _resolve_legacy_aegis_guidance(
        control_guidance=control_guidance,
        advisory_guidance=advisory_guidance,
        legacy_guidance=normalized.get("aegis_guidance"),
    )
    normalized["model_selection"] = _normalize_model_selection(normalized)
    return normalized


def build_run_payload_base(
    *,
    task: str,
    schema_version: int = 1,
    patch_operation: dict[str, Any] | None = None,
    model_selection: dict[str, Any] | None = None,
    control_guidance: dict[str, Any] | None = None,
    advisory_guidance: dict[str, Any] | None = None,
    aegis_guidance: dict[str, Any] | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = dict(extra_fields)
    payload["task"] = task
    payload["schema_version"] = int(schema_version)
    if patch_operation is not None:
        payload["patch_operation"] = patch_operation
    if model_selection is not None:
        payload["model_selection"] = model_selection
    payload["control_guidance"] = control_guidance
    payload["advisory_guidance"] = advisory_guidance
    payload["aegis_guidance"] = aegis_guidance
    return normalize_run_payload(payload)

