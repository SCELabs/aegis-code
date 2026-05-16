from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.secrets import resolve_key


def _resolve_key_available(environment: dict[str, Any] | None) -> bool:
    if isinstance(environment, dict) and "key_available" in environment:
        return bool(environment.get("key_available"))
    cwd_raw = environment.get("cwd") if isinstance(environment, dict) else None
    cwd = cwd_raw if isinstance(cwd_raw, Path) else Path.cwd()
    return bool(resolve_key("AEGIS_API_KEY", cwd.resolve()))


def _resolve_control_setting(options: Any, config: Any) -> tuple[Any, str]:
    for attr in ("control_enabled", "aegis_control_enabled"):
        if hasattr(options, attr):
            value = getattr(options, attr)
            if value is not None:
                return value, "option"
    return getattr(config.aegis, "control_enabled", "auto"), "config"


def resolve_control_state(options: Any, config: Any, environment: dict[str, Any] | None = None) -> dict[str, Any]:
    key_available = _resolve_key_available(environment)
    setting, source = _resolve_control_setting(options, config)
    explicit_auto = False

    if isinstance(setting, bool):
        requested = setting
        mode = "enabled" if setting else "disabled"
    else:
        lowered = str(setting).strip().lower()
        if lowered == "auto":
            requested = key_available
            mode = "auto"
            explicit_auto = True
        elif lowered in {"true", "1", "yes", "on"}:
            requested = True
            mode = "enabled"
        elif lowered in {"false", "0", "no", "off"}:
            requested = False
            mode = "disabled"
        else:
            requested = key_available
            mode = "auto"

    if requested:
        if mode == "auto":
            reason = "auto_enabled"
        else:
            reason = "enabled_by_option" if source == "option" else "enabled_by_config"
    else:
        if explicit_auto and not key_available:
            reason = "no_api_key"
        else:
            reason = "disabled_by_option" if source == "option" else "disabled_by_config"

    return {
        "enabled": bool(requested),
        "requested": bool(requested),
        "reason": reason,
        "mode": mode,
        "source": source,
        "key_available": bool(key_available),
    }


def control_requested(options: Any, config: Any, environment: dict[str, Any] | None = None) -> bool:
    state = resolve_control_state(options=options, config=config, environment=environment)
    return bool(state.get("requested", False))
