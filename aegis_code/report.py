from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths


def write_reports(payload: dict[str, Any], cwd: Path | None = None) -> dict[str, Path]:
    paths = project_paths(cwd)
    paths["runs_dir"].mkdir(parents=True, exist_ok=True)
    history_dir = paths["runs_dir"] / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    md_content = render_markdown_report(payload)
    history_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".json"
    history_path = history_dir / history_name
    history_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    paths["latest_json"].write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    paths["latest_md"].write_text(md_content, encoding="utf-8")
    return {"json": paths["latest_json"], "md": paths["latest_md"], "history_json": history_path}


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
    patch_quality = payload.get("patch_quality")
    task_driven_patch_proposal = bool(payload.get("task_driven_patch_proposal", False))
    verification = payload.get("verification", {})
    retry_policy = payload.get("retry_policy", {})
    symptoms = payload.get("symptoms", [])
    test_attempts = payload.get("test_attempts", [])
    project_context = payload.get("project_context", {}) or {}
    adapter = payload.get("adapter", {}) or {}
    applied_guidance = payload.get("applied_aegis_guidance", {}) or {}
    key_usage = payload.get("key_usage", []) if isinstance(payload.get("key_usage", []), list) else []

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
        "## Verification",
        "",
        f"- Available: `{verification.get('available', False)}`",
        f"- Detected stack: `{verification.get('detected_stack', 'unknown')}`",
        f"- Test command: `{verification.get('test_command', 'none')}`",
        f"- Confidence: `{verification.get('confidence', 'low')}`",
        f"- Reason: `{verification.get('reason', 'n/a')}`",
        "",
        "## Runtime Control",
        "",
        f"- Selected mode: `{(payload.get('runtime_policy', {}) or {}).get('selected_mode', 'n/a')}`",
        f"- Reason: `{(payload.get('runtime_policy', {}) or {}).get('reason', 'default')}`",
        (
            f"- Budget remaining: `${float((payload.get('budget_state', {}) or {}).get('remaining_estimate', 0.0)):.2f}`"
            if bool((payload.get('budget_state', {}) or {}).get("available", False))
            else "- Budget: not set"
        ),
        f"- Context available: `{bool((payload.get('project_context', {}) or {}).get('available', False))}`",
        "",
        "## Aegis Control",
        "",
        f"- Status: `{adapter.get('control_status', 'disabled')}`",
        f"- Reason: `{adapter.get('control_reason', adapter.get('fallback_reason', 'n/a'))}`",
        f"- Client available: `{bool(adapter.get('aegis_client_available', False))}`",
        f"- Execution: `{adapter.get('execution', 'local')}`",
        f"- Mutation: `{'confirm-only' if str(adapter.get('mutation', 'confirm_only')) == 'confirm_only' else adapter.get('mutation', 'confirm_only')}`",
        (
            f"- Error type: `{adapter.get('error_type')}`"
            if adapter.get("error_type")
            else "- Error type: `none`"
        ),
        (
            f"- Error: `{adapter.get('error_message')}`"
            if adapter.get("error_message")
            else "- Error: `none`"
        ),
        "",
        "## Project Context",
        "",
        f"- Available: `{project_context.get('available', False)}`",
        f"- Total chars: `{project_context.get('total_chars', 0)}`",
        f"- Included paths: `{', '.join(project_context.get('included_paths', [])) or 'none'}`",
        "",
        "## Applied Aegis Guidance",
        "",
        f"- Model tier override: `{applied_guidance.get('model_tier_override') or 'none'}`",
        f"- Max retries applied: `{applied_guidance.get('max_retries_applied', 0)}`",
        f"- Escalation allowed: `{bool(applied_guidance.get('escalation_allowed', False))}`",
        f"- Context mode: `{applied_guidance.get('context_mode', 'balanced')}`",
        "",
        "## Key Usage",
        "",
        "",
        "## Commands Run",
        "",
    ]
    if key_usage:
        for item in key_usage:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('name', '')}: source={item.get('source', 'missing')}, used_for={item.get('used_for', 'unknown')}, present={bool(item.get('present', False))}"
                )
    else:
        lines.append("- none")
    lines.append("")
    if not verification.get("available", False):
        lines.append("- No verification command was available, so no fix can be verified.")
        lines.append("")

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
    elif str(patch_diff.get("status", "")) == "generated":
        lines.append("- Status: `generated`")
        lines.append(f"- Provider: `{patch_diff.get('provider', 'unknown')}`")
        lines.append(f"- Model: `{patch_diff.get('model', 'unknown')}`")
        lines.append(f"- Regeneration attempted: `{bool(patch_diff.get('regeneration_attempted', False))}`")
        lines.append(f"- Aegis corrective control: `{patch_diff.get('corrective_control_status', 'not_triggered')}`")
        lines.append(f"- Path: `{patch_diff.get('path', '')}`")
        lines.append(f"- Syntactic valid: `{patch_diff.get('syntactic_valid')}`")
        if patch_diff.get("syntactic_error"):
            lines.append(f"- Syntactic error: `{patch_diff.get('syntactic_error')}`")
        preview = str(patch_diff.get("preview", "") or "")
        lines.append("- Preview:")
        lines.append("```diff")
        lines.append(preview[:800] if preview else "(empty)")
        lines.append("```")
    elif str(patch_diff.get("status", "")) == "invalid":
        lines.append("- Status: `invalid`")
        lines.append(f"- Regeneration attempted: `{bool(patch_diff.get('regeneration_attempted', False))}`")
        lines.append(f"- Aegis corrective control: `{patch_diff.get('corrective_control_status', 'not_triggered')}`")
        final_invalid_reason = patch_diff.get("final_invalid_reason", patch_diff.get("error"))
        if final_invalid_reason:
            lines.append(f"- Reason: `{final_invalid_reason}`")
        if patch_diff.get("error"):
            lines.append(f"- Error: `{patch_diff.get('error')}`")
        if patch_diff.get("invalid_diff_path"):
            lines.append(f"- Invalid diff path: `{patch_diff.get('invalid_diff_path')}`")
        lines.append("- Note: Diff failed validation and cannot be applied.")
    else:
        lines.append("- Status: `unavailable`")
        if patch_diff.get("provider"):
            lines.append(f"- Provider: `{patch_diff.get('provider')}`")
        if patch_diff.get("model"):
            lines.append(f"- Model: `{patch_diff.get('model')}`")
        lines.append(f"- Regeneration attempted: `{bool(patch_diff.get('regeneration_attempted', False))}`")
        lines.append(f"- Aegis corrective control: `{patch_diff.get('corrective_control_status', 'not_triggered')}`")
        if patch_diff.get("error"):
            lines.append(f"- Error: `{patch_diff.get('error')}`")

    if patch_diff.get("attempted", False) and patch_diff.get("plan_consistent") is not None:
        lines.extend(
            [
                "",
                "## Plan Consistency",
                "",
                f"- Consistent: `{bool(patch_diff.get('plan_consistent', True))}`",
            ]
        )
        missing_targets = patch_diff.get("plan_missing_targets", [])
        if isinstance(missing_targets, list) and missing_targets:
            lines.append("- Missing targets:")
            for path in missing_targets:
                lines.append(f"  - `{path}`")
        else:
            lines.append("- Missing targets: none")

    regeneration = patch_diff.get("regeneration", {}) if isinstance(patch_diff.get("regeneration"), dict) else {}
    lines.extend(
        [
            "",
            "## Patch Regeneration",
            "",
            f"- Triggered: `{bool(regeneration.get('triggered', False))}`",
            f"- Reason: `{patch_diff.get('regeneration_trigger_reason', regeneration.get('trigger_reason', regeneration.get('reason', 'none')))}`",
            f"- Attempt: `{int(regeneration.get('attempt', 1 if regeneration.get('attempted', False) else 0))}`",
            f"- Aegis corrective control: `{regeneration.get('corrective_control_status', patch_diff.get('corrective_control_status', 'not_triggered'))}`",
            f"- Result: `{regeneration.get('result', regeneration.get('final_status', patch_diff.get('status', 'unknown')))}`",
        ]
    )
    if str(regeneration.get("result", "")) in {"invalid", "timeout"} and regeneration.get("regenerated_invalid_reason"):
        lines.append(f"- Regenerated invalid reason: `{regeneration.get('regenerated_invalid_reason')}`")

    if str(patch_diff.get("status", "")) == "invalid":
        lines.extend(
            [
                "",
                "## Patch Quality",
                "",
                "- Patch quality: invalid (not evaluated)",
            ]
        )
    elif patch_quality:
        lines.extend(
            [
                "",
                "## Patch Quality",
                "",
                f"- Grounded: `{patch_quality.get('grounded', False)}`",
                f"- Relevant files: `{patch_quality.get('relevant_files', False)}`",
                f"- Confidence: `{patch_quality.get('confidence', 0.0)}`",
            ]
        )
        issues = patch_quality.get("issues", [])
        if issues:
            lines.append(f"- Issues: `{', '.join(str(item) for item in issues)}`")
        else:
            lines.append("- Issues: none")

    if task_driven_patch_proposal:
        lines.extend(
            [
                "",
                "## Task-Driven Patch Proposal",
                "",
                f"- Task: `{payload.get('task', '')}`",
                "- Note: no test failures detected.",
                f"- Strategy: {patch_plan.get('strategy', 'n/a')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Next Steps",
            "",
            "- Aegis Code runs a controlled execution loop with optional proposal-only patch diffs and deterministic patch-quality scoring.",
            "- No file edits or patch applications occur without explicit confirmation.",
            "- Use the report output, diff proposal, and patch-quality score to guide the next supervised action.",
            "",
        ]
    )
    return "\n".join(lines)


def read_latest_markdown(cwd: Path | None = None) -> tuple[Path, str] | None:
    path = project_paths(cwd)["latest_md"]
    if not path.exists():
        return None
    return path, path.read_text(encoding="utf-8")
