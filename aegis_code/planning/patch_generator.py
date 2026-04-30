from __future__ import annotations

from typing import Any

def _is_test_generation_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return False
    verification_only = ("run tests", "execute tests", "check tests")
    if any(phrase in lowered for phrase in verification_only):
        return False
    generation_phrases = (
        "add test",
        "add tests",
        "write test",
        "write tests",
        "generate test",
        "generate tests",
        "test for",
        "tests for",
        "coverage",
        "verify behavior",
        "assert",
    )
    return any(phrase in lowered for phrase in generation_phrases)


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
    test_task = _is_test_generation_task(task)
    if not failures:
        return {
            "strategy": f"No failures detected for task '{task}'. No patch required.",
            "confidence": 0.95,
            "proposed_changes": [],
            "task_type": "test_generation" if test_task else "general",
        }

    guidance = str(aegis_decision.get("context_mode", "balanced"))
    strategy = (
        f"Address {len(failures)} pytest failure(s) with {guidance} context and targeted edits only."
    )
    if test_task:
        strategy += (
            " Prefer test-only edits. Do not change source files unless explicitly requested. "
            "Keep imports at the top of test files and keep hunks minimal/valid."
        )
    if sll_analysis and sll_analysis.get("available", False):
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
                "reason": f"Pytest reported: {failure.get('error', 'Unknown failure')}",
            }
        )

    confidence = 0.55 if proposed_changes else 0.35
    if sll_analysis and sll_analysis.get("available", False):
        max_risk = max(
            float(sll_analysis.get("collapse_risk", 0.0)),
            float(sll_analysis.get("fragmentation_risk", 0.0)),
            float(sll_analysis.get("drift_risk", 0.0)),
            float(sll_analysis.get("stable_random_risk", 0.0)),
        )
        confidence = max(0.2, min(0.9, confidence + (1.0 - max_risk) * 0.2))

    plan = {
        "strategy": strategy,
        "confidence": round(confidence, 3),
        "proposed_changes": proposed_changes,
        "task_type": "test_generation" if test_task else "general",
    }
    if test_task:
        target_file = next(
            (
                str(item.get("file", "")).strip()
                for item in proposed_changes
                if isinstance(item, dict) and str(item.get("file", "")).strip().startswith("tests/")
            ),
            "",
        )
        if target_file:
            plan["target_file"] = target_file
    return plan
