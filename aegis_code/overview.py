from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.budget import get_budget_state
from aegis_code.config import load_config, project_paths
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.context_state import load_runtime_context
from aegis_code.policy import get_mode_reason, select_runtime_mode


def build_overview(cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    cfg = load_config(root)
    caps = detect_capabilities(root)
    budget = get_budget_state(root)
    context = load_runtime_context(root)
    final_mode = select_runtime_mode(cfg.mode, root)
    reason = get_mode_reason(cfg.mode, final_mode, root)
    paths = project_paths(root)
    latest_found = paths["latest_json"].exists()
    backups_dir = paths["aegis_dir"] / "backups"
    backup_count = 0
    if backups_dir.exists():
        backup_count = len([item for item in backups_dir.iterdir() if item.is_dir()])
    return {
        "stack": str(caps.get("detected_stack") or "unknown"),
        "verification": str(cfg.commands.test.strip() or "n/a"),
        "budget": budget,
        "context": {
            "available": bool(context.get("available", False)),
            "file_count": len(context.get("included_paths", [])),
            "total_chars": int(context.get("total_chars", 0) or 0),
        },
        "runtime_mode": final_mode,
        "runtime_reason": reason,
        "latest_run": "found" if latest_found else "missing",
        "backups": backup_count,
    }


def format_overview(data: dict[str, Any]) -> str:
    budget = data.get("budget", {}) or {}
    if budget.get("available", False):
        remaining = float(budget.get("remaining_estimate", 0.0) or 0.0)
        limit = float(budget.get("limit", 0.0) or 0.0)
        budget_text = f"${remaining:.2f} / ${limit:.2f}"
    else:
        budget_text = "not set"
    context = data.get("context", {}) or {}
    return "\n".join(
        [
            "Aegis Code Overview",
            f"- Stack: {data.get('stack', 'unknown')}",
            f"- Verification: {data.get('verification', 'n/a')}",
            f"- Budget: {budget_text}",
            (
                f"- Context: {'available' if context.get('available', False) else 'missing'}, "
                f"{int(context.get('file_count', 0) or 0)} files, {int(context.get('total_chars', 0) or 0)} chars"
            ),
            f"- Runtime mode: {data.get('runtime_mode', 'balanced')}",
            f"- Runtime reason: {data.get('runtime_reason', 'default')}",
            f"- Latest run: {data.get('latest_run', 'missing')}",
            f"- Backups: {int(data.get('backups', 0) or 0)}",
        ]
    )
