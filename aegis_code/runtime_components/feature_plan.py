from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.runtime_components.plan_consistency import _normalize_rel_path


def _is_explicit_multi_file_patch(*, explicit_scope_active: bool, explicit_scope: dict[str, Any], command: str) -> bool:
    explicit_scope_targets = [_normalize_rel_path(str(item)) for item in explicit_scope.get("allowed_targets", []) if str(item).strip()] if isinstance(explicit_scope.get("allowed_targets", []), list) else []
    return bool(
        str(command or "").strip().lower() == "patch"
        and explicit_scope_active
        and len(explicit_scope_targets) > 1
    )


def _build_feature_plan(
    *,
    command: str,
    requested_operation: str,
    explicit_scope_active: bool,
    explicit_scope: dict[str, Any],
    patch_plan: dict[str, Any],
    cwd: Path,
    task_text: str,
    baseline_healthy: bool,
) -> dict[str, Any] | None:
    if str(command or "").strip().lower() != "patch":
        return None
    if requested_operation == "append":
        return None
    if not explicit_scope_active:
        return None
    if not baseline_healthy:
        return None
    task_type = str(patch_plan.get("task_type", "") or "general")
    if "fix failing tests in " in str(task_text or "").lower():
        return None
    scope_targets = [
        _normalize_rel_path(str(item))
        for item in explicit_scope.get("allowed_targets", [])
        if str(item).strip()
    ] if isinstance(explicit_scope.get("allowed_targets", []), list) else []
    if task_type == "docs_task" and scope_targets and all(path == "README.md" or path.startswith("docs/") for path in scope_targets):
        return None
    if len(scope_targets) <= 1:
        return None

    proposed_changes = patch_plan.get("proposed_changes", []) if isinstance(patch_plan.get("proposed_changes", []), list) else []
    proposed_by_file: dict[str, dict[str, Any]] = {}
    for item in proposed_changes:
        if not isinstance(item, dict):
            continue
        path = _normalize_rel_path(str(item.get("file", "") or ""))
        if path and path not in proposed_by_file:
            proposed_by_file[path] = item

    allowed_ops = [
        str(item).strip().lower()
        for item in explicit_scope.get("allowed_operations", [])
        if str(item).strip()
    ] if isinstance(explicit_scope.get("allowed_operations", []), list) else []
    allow_new = bool(explicit_scope.get("allow_new_files", False))

    steps: list[dict[str, Any]] = []
    for idx, target in enumerate(scope_targets, start=1):
        op = "replace"
        if allowed_ops == ["create"]:
            op = "create"
        elif "create" in allowed_ops and "replace" not in allowed_ops:
            op = "create"
        elif allow_new and "create" in allowed_ops:
            exists = ((cwd / target).resolve()).exists()
            op = "replace" if exists else "create"
        change = proposed_by_file.get(target, {})
        description = str(change.get("description", "") or "").strip()
        intent = description or f"Apply requested task changes to {target}."
        steps.append(
            {
                "id": f"step_{idx}",
                "target_file": target,
                "operation": op,
                "intent": intent,
                "max_changed_lines": 300,
                "status": "planned",
            }
        )

    return {
        "available": True,
        "kind": "phase1_planning",
        "steps": steps,
    }

