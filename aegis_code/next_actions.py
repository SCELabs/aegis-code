from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_code.budget import get_budget_state
from aegis_code.config import project_paths
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.context_state import show_context
from aegis_code.workspace import load_workspace


def _latest_run_payload(cwd: Path) -> dict[str, Any] | None:
    latest_path = project_paths(cwd)["latest_json"]
    if not latest_path.exists():
        return None
    try:
        payload = json.loads(latest_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _read_signals(cwd: Path) -> dict[str, Any]:
    paths = project_paths(cwd)
    config_exists = paths["config_path"].exists()

    capabilities = detect_capabilities(cwd)
    verification_available = bool(capabilities.get("verification_available", False)) and bool(
        str(capabilities.get("test_command", "") or "").strip()
    )

    context = show_context(cwd)
    context_available = bool(context.get("exists", False))

    latest_payload = _latest_run_payload(cwd)
    latest_run_exists = latest_payload is not None

    failures = latest_payload.get("failures", {}) if latest_payload else {}
    if not isinstance(failures, dict):
        failures = {}
    failure_count = int(failures.get("failure_count", 0) or 0)

    patch_diff = latest_payload.get("patch_diff", {}) if latest_payload else {}
    if not isinstance(patch_diff, dict):
        patch_diff = {}
    patch_available = bool(patch_diff.get("available", False))
    patch_path = str(patch_diff.get("path", "") or "")

    budget = get_budget_state(cwd)
    budget_remaining = budget.get("remaining_estimate")
    if budget_remaining is not None:
        budget_remaining = float(budget_remaining)

    workspace_exists = load_workspace(cwd) is not None

    return {
        "config_exists": config_exists,
        "verification_available": verification_available,
        "context_available": context_available,
        "latest_run_exists": latest_run_exists,
        "failure_count": failure_count,
        "patch_available": patch_available,
        "patch_path": patch_path,
        "budget_remaining": budget_remaining,
        "workspace_exists": workspace_exists,
    }


def _action(title: str, command: str, reason: str) -> dict[str, str]:
    return {"title": title, "command": command, "reason": reason}


def build_next_actions(cwd: Path) -> dict:
    signals = _read_signals(cwd)
    actions: list[dict[str, str]] = []

    if not signals["config_exists"]:
        actions.append(
            _action(
                "Initialize Aegis project files",
                "aegis-code init",
                "Project config is missing at .aegis/aegis-code.yml.",
            )
        )

    if not signals["verification_available"]:
        actions.append(
            _action(
                "Configure verification command",
                "configure commands.test in .aegis/aegis-code.yml",
                "No verification command is available for deterministic checks.",
            )
        )

    if not signals["context_available"]:
        actions.append(
            _action(
                "Refresh project context",
                "aegis-code context refresh",
                "Project context files are missing.",
            )
        )

    if not signals["latest_run_exists"]:
        actions.append(
            _action(
                "Run an initial task",
                'aegis-code "<task>"',
                "No latest run report exists yet.",
            )
        )
    elif signals["failure_count"] > 0:
        actions.append(
            _action(
                "Address latest failures",
                "aegis-code fix",
                "Latest run recorded test failures.",
            )
        )
    elif signals["patch_available"]:
        patch_path = signals["patch_path"] or "<path>"
        actions.append(
            _action(
                "Review proposed patch diff",
                f"aegis-code apply --check {patch_path}",
                "Latest run includes an available patch diff.",
            )
        )

    if signals["budget_remaining"] is not None and signals["budget_remaining"] < 0.10:
        actions.append(
            _action(
                "Check budget guardrails",
                "aegis-code budget status",
                "Remaining budget is low; runtime may select cheapest mode.",
            )
        )

    if not actions:
        actions.append(
            _action(
                "Inspect project structure",
                'aegis-code "analyze project structure"',
                "Core local signals are healthy and no blocking issue was detected.",
            )
        )
        if signals["workspace_exists"]:
            actions.append(
                _action(
                    "Review multi-project state",
                    "aegis-code workspace overview",
                    "Workspace file is present and can provide cross-project status.",
                )
            )

    actions = actions[:5]

    return {
        "actions": actions,
        "signals": {
            "config_exists": signals["config_exists"],
            "verification_available": signals["verification_available"],
            "context_available": signals["context_available"],
            "latest_run_exists": signals["latest_run_exists"],
            "failure_count": signals["failure_count"],
            "budget_remaining": signals["budget_remaining"],
        },
    }


def format_next_actions(data: dict) -> str:
    actions = data.get("actions", [])
    signals = data.get("signals", {})

    lines = ["Suggested next actions:", ""]
    for idx, item in enumerate(actions, start=1):
        lines.append(f"{idx}. {item.get('title', '')}")
        lines.append(f"   command: {item.get('command', '')}")
        lines.append(f"   reason: {item.get('reason', '')}")
        lines.append("")

    budget_remaining = signals.get("budget_remaining")
    budget_display = "n/a" if budget_remaining is None else str(budget_remaining)

    lines.extend(
        [
            "Signals:",
            f"- Config: {'found' if signals.get('config_exists', False) else 'missing'}",
            f"- Verification: {'available' if signals.get('verification_available', False) else 'missing'}",
            f"- Context: {'available' if signals.get('context_available', False) else 'missing'}",
            f"- Latest run: {'found' if signals.get('latest_run_exists', False) else 'missing'}",
            f"- Failures: {int(signals.get('failure_count', 0) or 0)}",
            f"- Budget remaining: {budget_display}",
        ]
    )

    return "\n".join(lines)
