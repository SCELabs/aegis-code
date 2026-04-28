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
    failures = payload.get("failures", {})
    final_failures = payload.get("final_failures", failures)
    initial_failures = payload.get("initial_failures", {})
    failure_context = payload.get("failure_context", {})
    sll_analysis = payload.get("sll_analysis")
    patch_plan = payload.get("patch_plan", {})
    patch_diff = payload.get("patch_diff", {})
    retry_policy = payload.get("retry_policy", {})
    symptoms = payload.get("symptoms", [])
    test_attempts = payload.get("test_attempts", [])

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
            "## Test Attempts",
            "",
        ]
    )

    if test_attempts:
        for attempt in test_attempts:
            attempt_failures = attempt.get("failures", {}) if isinstance(attempt.get("failures", {}), dict) else {}
            lines.append(
                f"- Attempt `{attempt.get('attempt', '?')}` | status={attempt.get('status')} | exit={attempt.get('exit_code')} | failure_count={attempt_failures.get('failure_count', 0)}"
            )
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Synthesized Symptoms",
            "",
        ]
    )

    if symptoms:
        for symptom in symptoms:
            lines.append(f"- `{symptom}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Retry Policy",
            "",
            f"- Max retries: `{retry_policy.get('max_retries', 0)}`",
            f"- Allow escalation: `{retry_policy.get('allow_escalation', False)}`",
            f"- Retry attempted: `{retry_policy.get('retry_attempted', False)}`",
            f"- Retry count: `{retry_policy.get('retry_count', 0)}`",
            f"- Stopped reason: `{retry_policy.get('stopped_reason', 'n/a')}`",
            "",
            "## Final Failure State",
            "",
        ]
    )

    lines.append(
        f"- Initial failure count: `{initial_failures.get('failure_count', 0)}`"
    )
    lines.append(
        f"- Final failure count: `{final_failures.get('failure_count', 0)}`"
    )
    failed_tests = final_failures.get("failed_tests", [])
    if failed_tests:
        for failure in failed_tests:
            lines.append(
                f"- `{failure.get('test_name', 'unknown')}` ({failure.get('file', '?')}:{failure.get('line')})"
            )

    lines.extend(
        [
            "",
            "## Failure Context",
            "",
        ]
    )

    context_files = failure_context.get("files", [])
    if context_files:
        lines.append(f"- Files captured: `{len(context_files)}`")
        for item in context_files:
            lines.append(f"- `{item.get('path', '')}`")
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Structural Analysis",
            "",
        ]
    )

    if sll_analysis and sll_analysis.get("available", False):
        lines.append(f"- Regime: `{sll_analysis.get('regime', 'unknown')}`")
        lines.append(f"- Collapse risk: `{sll_analysis.get('collapse_risk', 0.0)}`")
        lines.append(f"- Fragmentation risk: `{sll_analysis.get('fragmentation_risk', 0.0)}`")
        lines.append(f"- Drift risk: `{sll_analysis.get('drift_risk', 0.0)}`")
        lines.append(f"- Stable random risk: `{sll_analysis.get('stable_random_risk', 0.0)}`")
        mapped = [
            item
            for item in symptoms
            if item
            in {
                "fragmented_output",
                "degenerate_loop",
                "unstable_workflow",
                "ungrounded_output",
            }
        ]
        if mapped:
            lines.append(f"- Mapped symptoms: `{', '.join(mapped)}`")
    else:
        lines.append("- Not available")
        lines.append("- Optional dependency not installed/importable")
        lines.append("- Run `aegis-code --check-sll` to verify local setup")

    lines.extend(
        [
            "",
            "## Proposed Fix Plan",
            "",
            f"- Strategy: {patch_plan.get('strategy', 'No patch strategy generated.')}",
            f"- Confidence: `{patch_plan.get('confidence', 0.0)}`",
        ]
    )

    proposed_changes = patch_plan.get("proposed_changes", [])
    if proposed_changes:
        for change in proposed_changes:
            lines.append(
                f"- `{change.get('file', '')}` | {change.get('change_type', 'modify')} | {change.get('description', '')} | reason={change.get('reason', '')}"
            )
    else:
        lines.append("- No proposed changes")

    lines.extend(
        [
            "",
            "## Patch Diff Proposal",
            "",
        ]
    )

    if not patch_diff.get("attempted", False):
        lines.append("- Not attempted")
    elif patch_diff.get("available", False):
        lines.append(f"- Provider: `{patch_diff.get('provider', 'unknown')}`")
        lines.append(f"- Model: `{patch_diff.get('model', 'unknown')}`")
        lines.append(f"- Path: `{patch_diff.get('path', '')}`")
        preview = str(patch_diff.get("preview", "") or "")
        lines.append("- Preview:")
        lines.append("```diff")
        lines.append(preview[:800] if preview else "(empty)")
        lines.append("```")
    else:
        lines.append("- Attempted but unavailable")
        if patch_diff.get("provider"):
            lines.append(f"- Provider: `{patch_diff.get('provider')}`")
        if patch_diff.get("model"):
            lines.append(f"- Model: `{patch_diff.get('model')}`")
        if patch_diff.get("error"):
            lines.append(f"- Error: `{patch_diff.get('error')}`")

    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "- v0.4 runs a controlled execution loop with optional proposal-only patch diffs.",
            "- No file edits or patch applications are performed.",
            "- Use the report output and diff proposal to guide the next supervised action.",
            "",
        ]
    )
    return "\n".join(lines)


def read_latest_markdown(cwd: Path | None = None) -> tuple[Path, str] | None:
    path = project_paths(cwd)["latest_md"]
    if not path.exists():
        return None
    return path, path.read_text(encoding="utf-8")
