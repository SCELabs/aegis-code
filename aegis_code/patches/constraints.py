from __future__ import annotations

import re
from typing import Any


_TESTS_ONLY_PHRASES = (
    "tests only",
    "test only",
    "write tests only",
    "do not modify source files",
    "do not modify source",
)


def detect_named_test_file(task: str) -> str:
    text = str(task or "").replace("\\", "/")
    match = re.search(r"(tests/[A-Za-z0-9_./-]+\.py)", text)
    if not match:
        return ""
    return match.group(1).strip()


def is_tests_only_task(task: str, task_type: str) -> bool:
    if str(task_type or "").strip().lower() == "test_generation":
        return True
    lowered = str(task or "").lower().strip()
    return any(phrase in lowered for phrase in _TESTS_ONLY_PHRASES)


def build_tests_only_provider_instructions(task: str, target_file: str | None = None) -> list[str]:
    _ = task
    instructions = [
        "Append-only test addition unless the task explicitly asks to edit existing tests.",
        "Do not delete existing tests.",
        "Do not rewrite whole files.",
        "Do not replace imports unless required.",
        "Add the smallest possible test.",
        "Prefer appending a new test method/function near relevant existing tests.",
        "Output a valid unified diff only.",
        "Prefer modifying tests only.",
        "Do not modify source files unless explicitly requested.",
        "Keep diff hunks minimal and valid.",
        "Ensure unified diff hunk line counts match hunk headers.",
        "Use a real unified hunk header generated against the provided file content.",
        "Use a real unified diff hunk header with line numbers.",
        "Do not use placeholder hunk headers such as @@ ... @@.",
        "Do not include truncated context.",
    ]
    if target_file:
        instructions.extend(
            [
                f"Named target file: {target_file}",
                f"Allowed target: {target_file}",
                f"Modify only this file: {target_file}",
                "Do not touch any other files.",
            ]
        )
    else:
        instructions.append("Allowed targets: tests/**")
    instructions.append("Max deletions: 0")
    return instructions


def build_tests_only_insertion_hint(task: str, target_file: str | None = None) -> str:
    chosen = str(target_file or "").strip() or detect_named_test_file(task)
    if chosen:
        return "Append a new test method at the end of class TestAegisResult."
    return "Append a new test method at the end of class TestAegisResult."


def build_patch_constraints(task: str, task_type: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = context
    normalized_task_type = str(task_type or "").strip().lower() or "general"
    docs_task = normalized_task_type == "docs_task"
    tests_only = is_tests_only_task(task, normalized_task_type)
    named_file = detect_named_test_file(task)
    target_file = named_file or None
    allowed_targets: list[str] = [named_file] if named_file else (["tests/**"] if tests_only else [])
    append_only = bool(tests_only)
    max_deletions = 0 if tests_only else None
    allow_source_changes = not tests_only
    insertion_hint = build_tests_only_insertion_hint(task, target_file=target_file) if tests_only else None
    provider_instructions = build_tests_only_provider_instructions(task, target_file=target_file) if tests_only else []
    regeneration_instructions: list[str] = []
    if tests_only:
        regeneration_instructions = [
            "Modify only tests/ paths unless explicitly requested.",
            "Keep imports at top of test files.",
            "Replace placeholder tests cleanly; do not append imports after test functions.",
        ]
    return {
        "task_type": normalized_task_type,
        "tests_only": tests_only,
        "docs_task": docs_task,
        "allowed_targets": allowed_targets,
        "target_file": target_file,
        "append_only": append_only,
        "max_deletions": max_deletions,
        "allow_source_changes": allow_source_changes,
        "insertion_hint": insertion_hint,
        "provider_instructions": provider_instructions,
        "regeneration_instructions": regeneration_instructions,
    }

