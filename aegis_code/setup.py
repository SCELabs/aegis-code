from __future__ import annotations

import getpass
from pathlib import Path
import yaml

from aegis_code.aegis_client import DEFAULT_AEGIS_BASE_URL, resolve_base_url
from aegis_code.budget import get_budget_state
from aegis_code.config import ensure_project_files, load_config
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.onboard import run_onboard
from aegis_code.policy import build_runtime_policy_payload, get_mode_reason, select_runtime_mode
from aegis_code.provider_presets import apply_preset, detect_available_providers
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.secrets import resolve_key, resolve_key_source, set_key
from aegis_code.context_state import load_runtime_context
from aegis_code.probe import load_observed_capabilities


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    response = input(prompt).strip().lower()
    return response in {"", "y", "yes"}


def run_setup(
    cwd: Path,
    email: str | None = None,
    skip_aegis: bool = False,
    skip_provider: bool = False,
    skip_first_run: bool = False,
    assume_yes: bool = False,
) -> dict:
    created = ensure_project_files(cwd=cwd, force=False)
    initialized = bool(created.get("config_created", False) or created.get("project_model_created", False))

    aegis = {"attempted": False, "success": False, "reason": None, "scope": None, "base_url": None, "base_url_source": None}
    provider = {"detected": False, "recommended_preset": None, "applied_preset": None, "key_name": "OPENAI_API_KEY", "key_scope": None}
    first_run = {"attempted": False, "status": None}

    if skip_aegis:
        aegis["reason"] = "skipped"
    else:
        existing_key = resolve_key("AEGIS_API_KEY", cwd)
        if existing_key:
            aegis["success"] = True
            aegis["reason"] = "already_configured"
            resolved_base_url = str(resolve_base_url(cwd) or DEFAULT_AEGIS_BASE_URL).strip()
            existing_base_url = resolve_key("AEGIS_BASE_URL", cwd)
            if not existing_base_url and resolved_base_url:
                set_key("AEGIS_BASE_URL", resolved_base_url, cwd, scope="global")
            resolved_source = resolve_key_source("AEGIS_BASE_URL", cwd)
            aegis["base_url"] = resolved_source.get("value") or resolved_base_url
            aegis["base_url_source"] = resolved_source.get("source", "missing")
        else:
            selected_email = (email or "").strip()
            if not selected_email:
                if assume_yes:
                    aegis["reason"] = "email_required"
                else:
                    if _confirm("Connect Aegis control guidance? [Y/n] ", assume_yes=False):
                        selected_email = input("Email: ").strip()
                    else:
                        aegis["reason"] = "skipped"
            if selected_email:
                aegis["attempted"] = True
                onboard = run_onboard(selected_email, cwd, scope="global")
                if onboard.get("success", False):
                    aegis["success"] = True
                    aegis["reason"] = None
                    aegis["scope"] = str(onboard.get("scope", "global"))
                    resolved_base_url = str(resolve_base_url(cwd) or DEFAULT_AEGIS_BASE_URL).strip()
                    existing_base_url = resolve_key("AEGIS_BASE_URL", cwd)
                    should_set_base_url = True
                    if existing_base_url and str(existing_base_url).strip() and str(existing_base_url).strip() != resolved_base_url:
                        should_set_base_url = _confirm(
                            "AEGIS_BASE_URL already set. Overwrite with resolved value? [y/N] ",
                            assume_yes=False,
                        )
                    if should_set_base_url and resolved_base_url:
                        set_key("AEGIS_BASE_URL", resolved_base_url, cwd, scope="global")
                    resolved_source = resolve_key_source("AEGIS_BASE_URL", cwd)
                    aegis["base_url"] = resolved_source.get("value") or resolved_base_url
                    aegis["base_url_source"] = resolved_source.get("source", "missing")
                else:
                    aegis["success"] = False
                    aegis["reason"] = str(onboard.get("reason", "failed"))
            elif aegis["reason"] is None:
                aegis["reason"] = "email_required"

    if not skip_provider:
        provider_key = resolve_key("OPENAI_API_KEY", cwd)
        if not provider_key:
            should_configure = _confirm("Configure provider key now? [Y/n] ", assume_yes=assume_yes)
            if should_configure:
                value = getpass.getpass("OPENAI_API_KEY: ").strip() if not assume_yes else ""
                if value:
                    set_key("OPENAI_API_KEY", value, cwd, scope="global")
                    provider["key_scope"] = "global"
        detection = detect_available_providers(cwd)
        provider["detected"] = True
        provider["recommended_preset"] = detection.get("recommended_preset")
        recommended = provider["recommended_preset"]
        if isinstance(recommended, str) and recommended:
            should_apply = _confirm(
                f"Apply recommended provider preset '{recommended}'? [Y/n] ",
                assume_yes=assume_yes,
            )
            if should_apply:
                result = apply_preset(recommended, cwd)
                if result.get("applied", False):
                    provider["applied_preset"] = recommended
                    config_path = cwd / ".aegis" / "aegis-code.yml"
                    try:
                        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
                        raw = loaded if isinstance(loaded, dict) else {}
                        providers = raw.get("providers")
                        if not isinstance(providers, dict):
                            providers = {}
                        providers["enabled"] = True
                        providers.setdefault("provider", "openai")
                        providers.setdefault("api_key_env", "OPENAI_API_KEY")
                        raw["providers"] = providers
                        config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                    except Exception:
                        pass
    else:
        provider["detected"] = False

    if not skip_first_run:
        should_run = _confirm("Run first project analysis now? [Y/n] ", assume_yes=assume_yes)
        if should_run:
            first_run["attempted"] = True
            cfg = load_config(cwd)
            base_mode = cfg.mode
            final_mode = select_runtime_mode(base_mode, cwd=cwd)
            _ = get_mode_reason(base_mode, final_mode, cwd=cwd)
            project_context = load_runtime_context(cwd=cwd)
            budget_state = get_budget_state(cwd=cwd)
            runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=cwd)
            payload = run_task(
                options=TaskOptions(
                    task="analyze project structure",
                    mode=final_mode,
                    project_context=project_context,
                    budget_state=budget_state,
                    runtime_policy=runtime_policy,
                ),
                cwd=cwd,
            )
            first_run["status"] = str(payload.get("status")) if payload.get("status") is not None else None
        else:
            first_run["status"] = "skipped"
    else:
        first_run["status"] = "skipped"

    return {
        "initialized": initialized,
        "aegis": aegis,
        "provider": provider,
        "first_run": first_run,
    }


def check_setup(cwd: Path) -> dict:
    config_path = cwd / ".aegis" / "aegis-code.yml"
    initialized = config_path.exists()

    aegis_resolved = resolve_key_source("AEGIS_API_KEY", cwd)
    aegis_key = bool(aegis_resolved.get("present", False))
    base_url_resolved = resolve_key_source("AEGIS_BASE_URL", cwd)
    cfg_for_base_url = load_config(cwd)
    base_url_value = (
        str(base_url_resolved.get("value", "") or "").strip()
        if bool(base_url_resolved.get("present", False))
        else str(cfg_for_base_url.aegis.base_url or DEFAULT_AEGIS_BASE_URL).strip()
    )
    if bool(base_url_resolved.get("present", False)):
        base_url_source = str(base_url_resolved.get("source", "missing"))
    else:
        configured_base_url = str(cfg_for_base_url.aegis.base_url or "").strip()
        base_url_source = "config" if configured_base_url else "default"
    provider_key_name = "OPENAI_API_KEY"
    provider_resolved = resolve_key_source(provider_key_name, cwd)
    provider_key = bool(provider_resolved.get("present", False))

    aegis_control_status = "disabled"
    if initialized:
        cfg = load_config(cwd)
        control_setting = cfg.aegis.control_enabled
        if isinstance(control_setting, bool):
            control_requested = control_setting
        else:
            lowered = str(control_setting).strip().lower()
            if lowered == "auto":
                control_requested = aegis_key
            elif lowered in {"true", "1", "yes", "on"}:
                control_requested = True
            else:
                control_requested = False
        aegis_control_status = "enabled" if control_requested else "disabled"
        provider_preset = all(
            bool(str(value).strip())
            for value in (cfg.models.cheap, cfg.models.mid, cfg.models.premium)
        )
    else:
        provider_preset = False

    context_dir = cwd / ".aegis" / "context"
    context_available = context_dir.exists() and context_dir.is_dir() and any(context_dir.iterdir())
    latest_run = (cwd / ".aegis" / "runs" / "latest.json").exists()
    detected = detect_capabilities(cwd)
    observed = load_observed_capabilities(cwd)
    verification_available = bool(detected.get("verification_available", False))

    return {
        "initialized": initialized,
        "aegis_key": aegis_key,
        "aegis_key_source": str(aegis_resolved.get("source", "missing")),
        "aegis_base_url": base_url_value,
        "aegis_base_url_source": base_url_source,
        "aegis_control_status": aegis_control_status,
        "provider_key": provider_key,
        "provider_key_source": str(provider_resolved.get("source", "missing")),
        "provider_key_name": provider_key_name,
        "provider_preset": provider_preset,
        "context_available": context_available,
        "latest_run": latest_run,
        "verification_available": verification_available,
        "detected_stack": detected.get("detected_stack"),
        "package_manager": detected.get("package_manager"),
        "detected_test_command": detected.get("test_command"),
        "verification_confidence": detected.get("confidence"),
        "verification_reason": detected.get("reason"),
        "observed_capabilities_present": bool(observed is not None),
        "observed_selected_test_command": (
            str(observed.get("test_command", "") or observed.get("selected_test_command", "")).strip()
            if isinstance(observed, dict)
            else ""
        ),
    }
