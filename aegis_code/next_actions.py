from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths


def _latest_payload(cwd: Path) -> dict[str, Any] | None:
    latest = project_paths(cwd)["latest_json"]
    if not latest.exists():
        return None
    try:
        data = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _extract_payload(payload: dict[str, Any] | None, cwd: Path | None) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if cwd is not None:
        loaded = _latest_payload(cwd)
        if isinstance(loaded, dict):
            return loaded
    return {}


def _blocked_status(patch_diff: dict[str, Any]) -> bool:
    status = str(patch_diff.get("status", "") or "").strip().lower()
    return status in {"blocked", "hard_invalid", "invalid"}


def build_next_actions(payload: dict[str, Any], cwd: Path | None = None) -> dict:
    data = _extract_payload(payload, cwd)
    environment_issues = data.get("environment_issues", [])
    if not isinstance(environment_issues, list):
        environment_issues = []
    patch_diff = data.get("patch_diff", {}) if isinstance(data.get("patch_diff"), dict) else {}
    patch_quality = data.get("patch_quality", {}) if isinstance(data.get("patch_quality"), dict) else {}
    verification = data.get("verification", {}) if isinstance(data.get("verification"), dict) else {}
    final_failures = data.get("final_failures", {}) if isinstance(data.get("final_failures"), dict) else {}
    status = str(data.get("status", "") or "")

    patch_available = bool(patch_diff.get("available", False))
    patch_attempted = bool(patch_diff.get("attempted", False))
    patch_safety = str(patch_diff.get("apply_safety", "") or "").strip().upper()
    quality_safety = str(patch_quality.get("apply_safety", "") or "").strip().upper()
    verification_available = bool(verification.get("available", False))
    has_failure_count = "failure_count" in final_failures
    failure_count = int(final_failures.get("failure_count", 0) or 0)

    if len(environment_issues) > 0:
        actions = [
            "Resolve environment issues listed above",
            "Re-run: aegis-code doctor",
            "Then run: aegis-code probe --run",
        ]
        return {"actions": actions, "rule": "environment_issues"}

    if patch_safety in {"LOW", "BLOCKED"} or quality_safety in {"LOW", "BLOCKED"} or _blocked_status(patch_diff):
        actions = [
            "Do not apply this patch yet.",
            "Inspect why: aegis-code apply --check",
            "Regenerate carefully: aegis-code fix --max-cycles 1",
        ]
        return {"actions": actions, "rule": "blocked_or_low_patch"}

    if patch_available:
        actions = [
            "Inspect: aegis-code diff --stat",
            "Validate: aegis-code apply --check",
            "Apply safely: aegis-code apply --confirm --run-tests",
        ]
        return {"actions": actions, "rule": "patch_available"}

    if status == "budget_skipped":
        actions = [
            "Check budget: aegis-code budget status",
            "Raise or clear budget if appropriate: aegis-code budget set <amount>",
        ]
        return {"actions": actions, "rule": "budget_skipped"}

    if ("tests_failed" in status) or failure_count > 0:
        actions = [
            "Inspect failures: aegis-code report",
            "Generate bounded fix: aegis-code fix --max-cycles 1",
            "Apply only after check: aegis-code apply --check",
        ]
        return {"actions": actions, "rule": "tests_failed"}

    if ("tests_passed" in status) or (has_failure_count and failure_count == 0 and verification_available):
        actions = [
            "Review summary: aegis-code status",
            "Compare with previous run: aegis-code compare",
        ]
        return {"actions": actions, "rule": "tests_passed"}

    if patch_attempted and not patch_available:
        actions = [
            "Review report: aegis-code report",
            "Check setup: aegis-code doctor",
            "Retry with clearer scope or refreshed context: aegis-code context refresh",
        ]
        return {"actions": actions, "rule": "patch_attempted_unavailable"}

    if not verification_available:
        actions = [
            "Probe project capabilities: aegis-code probe --run",
            "Or set commands.test in .aegis/aegis-code.yml",
        ]
        return {"actions": actions, "rule": "no_verification"}

    actions = [
        "Review report: aegis-code report",
        "Check project status: aegis-code status",
    ]
    return {"actions": actions, "rule": "default"}


def format_next_actions(data: dict) -> str:
    actions = data.get("actions", [])
    lines = ["Next safe action:"]
    for idx, item in enumerate(actions, start=1):
        lines.append(f"{idx}. {str(item)}")
    return "\n".join(lines)
