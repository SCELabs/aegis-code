from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths


def write_reports(payload: dict[str, Any], cwd: Path | None = None) -> dict[str, Path]:
    paths = project_paths(cwd)
    paths["runs_dir"].mkdir(parents=True, exist_ok=True)

    md_content = render_markdown_report(payload)
    paths["latest_json"].write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    paths["latest_md"].write_text(md_content, encoding="utf-8")
    return {"json": paths["latest_json"], "md": paths["latest_md"]}


def render_markdown_report(payload: dict[str, Any]) -> str:
    budget = payload.get("budget", {})
    commands_run = payload.get("commands_run", [])
    repo_scan = payload.get("repo_scan", {})
    guidance = payload.get("aegis_execution", {})
    selected_tier = payload.get("selected_model_tier", "mid")
    selected_model = payload.get("selected_model", "unknown")

    lines = [
        "# Aegis Code Run Report",
        "",
        f"- Task: `{payload.get('task', '')}`",
        f"- Mode: `{payload.get('mode', '')}`",
        f"- Dry run: `{payload.get('dry_run', False)}`",
        "",
        "## Budget",
        "",
        f"- Total: `{budget.get('total', 0.0)}`",
        f"- Spent: `{budget.get('spent', 0.0)}`",
        f"- Remaining: `{budget.get('remaining', 0.0)}`",
        "",
        "## Model Selection",
        "",
        f"- Tier: `{selected_tier}`",
        f"- Model: `{selected_model}`",
        "",
        "## Aegis Execution Guidance",
        "",
        "```json",
        json.dumps(guidance, indent=2, sort_keys=True),
        "```",
        "",
        "## Repo Scan Summary",
        "",
        f"- File count: `{repo_scan.get('file_count', 0)}`",
        f"- Top-level directories: `{', '.join(repo_scan.get('top_level_directories', []))}`",
        "",
        "## Commands Run",
        "",
    ]

    if commands_run:
        for cmd in commands_run:
            lines.append(
                f"- `{cmd.get('name', 'command')}` | status={cmd.get('status')} | exit={cmd.get('exit_code')}"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "- v0.1 is planning/reporting only.",
            "- No file edits are performed in this version.",
            "- Use report output to guide the next manual or supervised action.",
            "",
        ]
    )
    return "\n".join(lines)


def read_latest_markdown(cwd: Path | None = None) -> tuple[Path, str] | None:
    path = project_paths(cwd)["latest_md"]
    if not path.exists():
        return None
    return path, path.read_text(encoding="utf-8")
