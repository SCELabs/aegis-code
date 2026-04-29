from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.budget import load_budget
from aegis_code.config import load_config
from aegis_code.context_state import load_runtime_context


def select_runtime_mode(config_mode: str, cwd: Path | None = None) -> str:
    budget = load_budget(cwd or Path.cwd())
    if not budget:
        return config_mode
    limit = float(budget.get("limit", 0.0) or 0.0)
    spent = float(budget.get("spent_estimate", 0.0) or 0.0)
    remaining = limit - spent
    if remaining < 0.10:
        return "cheapest"
    return config_mode


def get_mode_reason(config_mode: str, final_mode: str, cwd: Path | None = None) -> str:
    budget = load_budget(cwd or Path.cwd())
    if not budget:
        return "default"
    if final_mode == config_mode:
        return "default"
    limit = float(budget.get("limit", 0.0) or 0.0)
    spent = float(budget.get("spent_estimate", 0.0) or 0.0)
    remaining = limit - spent
    if final_mode == "cheapest" and remaining < 0.10:
        return "low_budget"
    return "policy_adjustment"


def build_runtime_policy_payload(
    config_mode: str,
    final_mode: str,
    cwd: Path | None = None,
) -> dict[str, Any]:
    root = cwd or Path.cwd()
    budget = load_budget(root)
    runtime_context = load_runtime_context(root)
    return {
        "requested_mode": config_mode,
        "selected_mode": final_mode,
        "reason": get_mode_reason(config_mode, final_mode, root),
        "budget_present": budget is not None,
        "context_available": bool(runtime_context.get("available", False)),
    }


def build_policy_status(cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    cfg = load_config(root)
    budget = load_budget(root)
    runtime_context = load_runtime_context(root)
    spent = float((budget or {}).get("spent_estimate", 0.0) or 0.0)
    limit = float((budget or {}).get("limit", 0.0) or 0.0) if budget else 0.0
    return {
        "mode": cfg.mode,
        "models": {
            "cheap": cfg.models.cheap,
            "mid": cfg.models.mid,
            "premium": cfg.models.premium,
        },
        "provider": {
            "enabled": cfg.providers.enabled,
            "name": cfg.providers.provider,
            "api_key_env": cfg.providers.api_key_env,
        },
        "budget": {
            "exists": budget is not None,
            "limit": limit,
            "spent_estimate": spent,
            "remaining_estimate": max(0.0, limit - spent),
        },
        "context": {
            "available": runtime_context.get("available", False),
            "total_chars": runtime_context.get("total_chars", 0),
            "included_paths": runtime_context.get("included_paths", []),
        },
        "verification": {"test_command": cfg.commands.test},
        "runtime_guards": [
            "Budget gates runtime/Aegis calls.",
            "Local operations are free.",
            "Context is capped before runtime use.",
        ],
    }


def format_policy_status(status: dict[str, Any]) -> str:
    models = status.get("models", {})
    provider = status.get("provider", {})
    budget = status.get("budget", {})
    context = status.get("context", {})
    verification = status.get("verification", {})
    guards = status.get("runtime_guards", [])
    lines = [
        "Runtime policy status:",
        f"- Mode: {status.get('mode', 'balanced')}",
        "- Model tiers:",
        f"  cheap: {models.get('cheap', '')}",
        f"  mid: {models.get('mid', '')}",
        f"  premium: {models.get('premium', '')}",
        "- Provider:",
        f"  enabled: {provider.get('enabled', False)}",
        f"  name: {provider.get('name', 'openai')}",
        f"  api_key_env: {provider.get('api_key_env', 'OPENAI_API_KEY')}",
        "- Budget:",
        f"  exists: {budget.get('exists', False)}",
        f"  limit: {budget.get('limit', 0.0)}",
        f"  spent_estimate: {budget.get('spent_estimate', 0.0)}",
        f"  remaining_estimate: {budget.get('remaining_estimate', 0.0)}",
        "- Context:",
        f"  available: {context.get('available', False)}",
        f"  total_chars: {context.get('total_chars', 0)}",
        f"  included_paths: {', '.join(context.get('included_paths', [])) or 'none'}",
        "- Verification:",
        f"  commands.test: {verification.get('test_command', '')}",
        "- Runtime guards:",
    ]
    for item in guards:
        lines.append(f"  - {item}")
    return "\n".join(lines)


def format_runtime_control_summary(
    runtime_policy: dict[str, Any] | None,
    budget_state: dict[str, Any] | None,
    project_context: dict[str, Any] | None,
) -> str:
    policy = runtime_policy or {}
    budget = budget_state or {}
    context = project_context or {}
    selected_mode = str(policy.get("selected_mode") or "n/a")
    reason = str(policy.get("reason") or "default")
    budget_available = bool(budget.get("available", False))
    remaining = budget.get("remaining_estimate")
    if budget_available and isinstance(remaining, (int, float)):
        budget_line = f"- Budget remaining: ${float(remaining):.2f} (control signal)"
    else:
        budget_line = "- Budget: not set"
    return "\n".join(
        [
            "Runtime Control:",
            f"- Selected mode: {selected_mode}",
            f"- Reason: {reason}",
            budget_line,
            "Budget affects runtime mode selection, not actual API cost.",
            f"- Context available: {'true' if bool(context.get('available', False)) else 'false'}",
        ]
    )
