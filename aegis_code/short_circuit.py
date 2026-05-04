from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.budget import can_spend, load_budget
from aegis_code.config import project_paths
from aegis_code.patches.apply_check import check_patch_file
from aegis_code.verification import resolve_verification_command

if TYPE_CHECKING:
    from aegis_code.runtime import TaskOptions


def _task_text(options: TaskOptions) -> str:
    return str(getattr(options, "task", "") or "").strip().lower()


def _is_verification_only_task(options: TaskOptions) -> bool:
    task = _task_text(options)
    return task in {"run tests", "check tests", "execute tests"}


def _task_implies_test_fix_or_validation(options: TaskOptions) -> bool:
    task = _task_text(options)
    phrases = (
        "fix test",
        "tests failed",
        "failing test",
        "validation",
        "verify",
        "run tests",
        "check tests",
        "execute tests",
    )
    return any(p in task for p in phrases)


def _latest_payload(cwd: Path) -> dict[str, Any] | None:
    latest = project_paths(cwd)["latest_json"]
    if not latest.exists():
        return None
    try:
        raw = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) else None


def _failure_signature(failures: dict[str, Any]) -> str:
    failed_tests = failures.get("failed_tests", []) if isinstance(failures, dict) else []
    items: list[str] = []
    if isinstance(failed_tests, list):
        for item in failed_tests:
            if not isinstance(item, dict):
                continue
            node = str(item.get("test_name", "") or "").strip()
            file_path = str(item.get("file", "") or "").replace("\\", "/").strip()
            err = str(item.get("error", "") or "").strip()
            if node:
                items.append(f"{node}|{file_path}|{err}")
    if not items:
        count = int((failures or {}).get("failure_count", 0) or 0)
        items.append(f"count={count}")
    normalized = "\n".join(sorted(items))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _has_repeated_failure_signature(cwd: Path) -> bool:
    latest = _latest_payload(cwd)
    if not isinstance(latest, dict):
        return False
    patch_diff = latest.get("patch_diff", {}) if isinstance(latest.get("patch_diff"), dict) else {}
    attempted = bool(patch_diff.get("attempted", False))
    status = str(latest.get("status", "") or "")
    final_failures = latest.get("final_failures", {}) if isinstance(latest.get("final_failures"), dict) else {}
    initial_failures = latest.get("initial_failures", {}) if isinstance(latest.get("initial_failures"), dict) else {}
    failed = ("tests_failed" in status) or int(final_failures.get("failure_count", 0) or 0) > 0
    if not (attempted and failed):
        return False
    return _failure_signature(initial_failures) == _failure_signature(final_failures)


def should_skip_provider(options: TaskOptions, cwd: Path) -> dict[str, Any]:
    if _is_verification_only_task(options):
        return {"skip": True, "reason": "verification_only", "action": "Run local tests only"}

    verification = resolve_verification_command(cwd)
    if (not bool(verification.get("available", False))) and _task_implies_test_fix_or_validation(options):
        return {
            "skip": True,
            "reason": "no_verification_available",
            "action": "Run: aegis-code probe --run OR set commands.test",
        }

    latest_diff = project_paths(cwd)["latest_diff"]
    if latest_diff.exists():
        checked = check_patch_file(latest_diff, cwd=cwd)
        if bool(checked.get("valid", False)) and not bool(checked.get("apply_blocked", False)):
            return {
                "skip": True,
                "reason": "existing_patch_available",
                "action": "Inspect/apply existing diff instead of regenerating",
            }

    if _has_repeated_failure_signature(cwd):
        return {
            "skip": True,
            "reason": "repeated_failure",
            "action": "Run bounded fix: aegis-code fix --max-cycles 1",
        }

    if load_budget(cwd) and not can_spend("provider_call", 0.01, cwd):
        return {
            "skip": True,
            "reason": "budget_exceeded",
            "action": "Check budget: aegis-code budget status",
        }

    return {"skip": False, "reason": "none", "action": None}
