from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths


def load_last_runs(cwd: Path | None = None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    runs_dir = project_paths(cwd)["runs_dir"]
    if not runs_dir.exists():
        return None, None

    history_dir = runs_dir / "history"
    if history_dir.exists():
        history_files = sorted([p for p in history_dir.glob("*.json") if p.is_file()], key=lambda p: p.name)
        if len(history_files) >= 2:
            prev = json.loads(history_files[-2].read_text(encoding="utf-8"))
            current = json.loads(history_files[-1].read_text(encoding="utf-8"))
            return prev, current

    files = sorted([p for p in runs_dir.glob("*.json") if p.is_file() and p.name != "latest.json"], key=lambda p: p.name)
    latest_path = project_paths(cwd)["latest_json"]
    if latest_path.exists():
        files = [p for p in files if p.resolve() != latest_path.resolve()]
        files.append(latest_path)

    if len(files) < 2:
        return None, json.loads(files[-1].read_text(encoding="utf-8")) if files else None

    prev = json.loads(files[-2].read_text(encoding="utf-8"))
    current = json.loads(files[-1].read_text(encoding="utf-8"))
    return prev, current


def _pick(run: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = run
    for part in path.split("."):
        if not isinstance(value, dict):
            return default
        value = value.get(part, default)
    return value


def build_comparison(prev: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "runtime_control.selected_mode": (
            _pick(prev, "runtime_policy.selected_mode", "n/a"),
            _pick(current, "runtime_policy.selected_mode", "n/a"),
        ),
        "runtime_control.reason": (
            _pick(prev, "runtime_policy.reason", "n/a"),
            _pick(current, "runtime_policy.reason", "n/a"),
        ),
        "model_tier": (
            _pick(prev, "selected_model_tier", "n/a"),
            _pick(current, "selected_model_tier", "n/a"),
        ),
        "max_retries": (
            _pick(prev, "retry_policy.max_retries", 0),
            _pick(current, "retry_policy.max_retries", 0),
        ),
        "escalation": (
            _pick(prev, "retry_policy.allow_escalation", False),
            _pick(current, "retry_policy.allow_escalation", False),
        ),
        "context_mode": (
            _pick(prev, "applied_aegis_guidance.context_mode", "balanced"),
            _pick(current, "applied_aegis_guidance.context_mode", "balanced"),
        ),
        "adapter.mode": (
            _pick(prev, "adapter.mode", "n/a"),
            _pick(current, "adapter.mode", "n/a"),
        ),
    }
    changes = {k: {"from": v[0], "to": v[1]} for k, v in fields.items() if v[0] != v[1]}
    return {"fields": fields, "changes": changes}


def format_comparison(data: dict[str, Any]) -> str:
    fields = data.get("fields", {})
    changes = data.get("changes", {})
    lines = ["Run Comparison", ""]
    if not changes:
        lines.append("No runtime behavior changes detected across the last two runs.")
        return "\n".join(lines)

    lines.append("Changed fields:")
    for key in (
        "runtime_control.selected_mode",
        "runtime_control.reason",
        "model_tier",
        "max_retries",
        "escalation",
        "context_mode",
        "adapter.mode",
    ):
        if key in changes:
            lines.append(f"- {key}: {changes[key]['from']} -> {changes[key]['to']}")
    lines.append("")
    lines.append("Current snapshot:")
    for key, (_, current) in fields.items():
        lines.append(f"- {key}: {current}")
    return "\n".join(lines)
