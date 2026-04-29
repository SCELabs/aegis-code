from __future__ import annotations

from pathlib import Path

from aegis_code.budget import get_budget_state
from aegis_code.config import ensure_project_files, load_config
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.onboard import run_onboard
from aegis_code.policy import build_runtime_policy_payload, get_mode_reason, select_runtime_mode
from aegis_code.provider_presets import apply_preset, detect_available_providers
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.secrets import resolve_key
from aegis_code.context_state import load_runtime_context


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

    aegis = {"attempted": False, "success": False, "reason": None}
    provider = {"detected": False, "recommended_preset": None, "applied_preset": None}
    first_run = {"attempted": False, "status": None}

    if skip_aegis:
        aegis["reason"] = "skipped"
    else:
        existing_key = resolve_key("AEGIS_API_KEY", cwd)
        if existing_key:
            aegis["success"] = True
            aegis["reason"] = "already_configured"
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
                onboard = run_onboard(selected_email, cwd)
                if onboard.get("success", False):
                    aegis["success"] = True
                    aegis["reason"] = None
                else:
                    aegis["success"] = False
                    aegis["reason"] = str(onboard.get("reason", "failed"))
            elif aegis["reason"] is None:
                aegis["reason"] = "email_required"

    if not skip_provider:
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

    aegis_key = bool(resolve_key("AEGIS_API_KEY", cwd))
    provider_key = any(
        bool(resolve_key(name, cwd))
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
        )
    )

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
    verification_available = bool(detect_capabilities(cwd).get("verification_available", False))

    return {
        "initialized": initialized,
        "aegis_key": aegis_key,
        "aegis_control_status": aegis_control_status,
        "provider_key": provider_key,
        "provider_preset": provider_preset,
        "context_available": context_available,
        "latest_run": latest_run,
        "verification_available": verification_available,
    }
