from __future__ import annotations

from typing import Any


def _normalize_rel_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./")


def _collect_plan_targets(patch_plan: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    proposed = patch_plan.get("proposed_changes", [])
    if not isinstance(proposed, list):
        return targets
    for change in proposed:
        if not isinstance(change, dict):
            continue
        file_value = _normalize_rel_path(str(change.get("file", "") or ""))
        if not file_value:
            continue
        change_type = str(change.get("change_type", "") or "").strip().lower()
        if change_type in {"task_intent", "note", "metadata"}:
            continue
        targets.add(file_value)
    return targets


def _collect_diff_targets(validation: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    files = validation.get("files", [])
    if not isinstance(files, list):
        return targets
    for item in files:
        if not isinstance(item, dict):
            continue
        old_path = item.get("old_path")
        new_path = item.get("new_path")
        if isinstance(old_path, str) and old_path:
            targets.add(_normalize_rel_path(old_path))
        if isinstance(new_path, str) and new_path:
            targets.add(_normalize_rel_path(new_path))
    return targets


def _infer_heuristic_targets(strategy: str, diff_text: str) -> set[str]:
    inferred: set[str] = set()
    lowered_strategy = str(strategy or "").lower()
    strategy_hints = (
        "add module",
        "create module",
        "add file",
        "new file",
        "helpers module",
    )
    if any(hint in lowered_strategy for hint in strategy_hints):
        inferred.add("src/helpers.py")

    for raw_line in str(diff_text or "").splitlines():
        if not raw_line.startswith("+") or raw_line.startswith("+++ "):
            continue
        line = raw_line[1:].strip()
        if line.startswith("import src.helpers") or line.startswith("from src.helpers import"):
            inferred.add("src/helpers.py")

    return inferred


def _compute_plan_consistency(
    patch_plan: dict[str, Any],
    validation: dict[str, Any],
    diff_text: str,
) -> tuple[bool, list[str]]:
    planned_targets = _collect_plan_targets(patch_plan)
    planned_targets.update(_infer_heuristic_targets(str(patch_plan.get("strategy", "") or ""), diff_text))
    if not planned_targets:
        return True, []
    diff_targets = _collect_diff_targets(validation)
    missing = sorted(path for path in planned_targets if path not in diff_targets)
    return not missing, missing

