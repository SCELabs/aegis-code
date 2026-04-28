from __future__ import annotations

from typing import Any


def _pick_target_file(
    failure_file: str,
    context_files: list[dict[str, Any]],
) -> str:
    for item in context_files:
        path = str(item.get("path", ""))
        if path and "tests" not in path.replace("\\", "/").split("/"):
            return path
    return failure_file


def generate_patch_plan(
    task: str,
    failures: list[dict[str, Any]],
    context: dict[str, Any],
    aegis_decision: dict[str, Any],
    sll_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    if not failures:
        return {
            "strategy": f"No failures detected for task '{task}'. No patch required.",
            "proposed_changes": [],
        }

    guidance = str(aegis_decision.get("context_mode", "balanced"))
    strategy = (
        f"Address {len(failures)} pytest failure(s) with {guidance} context and targeted edits only."
    )
    if sll_analysis:
        strategy += f" SLL regime='{sll_analysis.get('regime', 'unknown')}'."

    context_files = context.get("files", []) if isinstance(context.get("files", []), list) else []
    proposed_changes: list[dict[str, str]] = []
    seen_files: set[str] = set()

    for failure in failures:
        file_path = str(failure.get("file", "")).strip()
        if not file_path:
            continue

        target = _pick_target_file(file_path, context_files)

        if target in seen_files:
            continue
        seen_files.add(target)

        proposed_changes.append(
            {
                "file": target,
                "change_type": "modify",
                "description": f"Update logic to resolve failing test '{failure.get('test_name', '')}'.",
            }
        )

    return {"strategy": strategy, "proposed_changes": proposed_changes}
