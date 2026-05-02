from __future__ import annotations

from typing import Any

from aegis_code.providers.context_builder import (
    build_named_test_file_context,
    extract_named_test_file,
    line_safe_cap,
    shape_test_generation_context,
    trim_context,
)


def _line_safe_cap(content: str, limit: int) -> str:
    return line_safe_cap(content, limit)


def _is_docs_task(task: str, patch_plan: dict[str, Any]) -> bool:
    lowered = str(task or "").lower()
    if any(token in lowered for token in ("readme", "docs", "documentation")):
        return True
    proposed = patch_plan.get("proposed_changes", [])
    if isinstance(proposed, list):
        for item in proposed:
            if not isinstance(item, dict):
                continue
            path = str(item.get("file", "")).strip().lower().replace("\\", "/")
            if path == "readme.md" or path.startswith("docs/"):
                return True
    return False


def _strip_provider_prefix(model: str) -> str:
    if ":" not in model:
        return model
    return model.split(":", 1)[1]


def _trim_context(context: dict[str, Any], max_chars: int) -> dict[str, Any]:
    return trim_context(context, max_chars)


def _extract_named_test_file(task: str) -> str:
    return extract_named_test_file(task)


def _build_named_test_file_context(path: str, content: str) -> dict[str, Any]:
    return build_named_test_file_context(path, content)


def _shape_test_generation_context(
    *,
    task: str,
    context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> dict[str, Any]:
    return shape_test_generation_context(task=task, context=context, patch_plan=patch_plan)


def build_diff_prompt(
    *,
    task: str,
    failures: dict[str, Any],
    context: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
) -> str:
    test_constraints: list[str] = []
    regen_constraints: list[str] = []
    task_type = str(patch_plan.get("task_type", "")).strip().lower()
    target_file = str(patch_plan.get("target_file", "")).strip()
    raw_regen = patch_plan.get("regeneration_constraints", [])
    if isinstance(raw_regen, list):
        regen_constraints = [f"- {str(item)}" for item in raw_regen if str(item).strip()]
    if task_type == "test_generation":
        named_test_file = _extract_named_test_file(task)
        test_constraints = [
            "Test-generation guidance:",
            "- Append-only test addition unless the task explicitly asks to edit existing tests.",
            "- Do not delete existing tests.",
            "- Do not rewrite whole files.",
            "- Do not replace imports unless required.",
            "- Add the smallest possible test.",
            "- Prefer appending a new test method/function near relevant existing tests.",
            "- Output a valid unified diff only.",
            "- Prefer modifying tests only.",
            "- Do not modify source files unless explicitly requested.",
            "- Keep diff hunks minimal and valid.",
            "- Ensure unified diff hunk line counts match hunk headers.",
            "- Use a real unified hunk header generated against the provided file content.",
            "- Use a real unified diff hunk header with line numbers.",
            "- Do not use placeholder hunk headers such as @@ ... @@.",
            "- Do not include truncated context.",
        ]
        if named_test_file:
            test_constraints.extend(
                [
                    f"- Named target file: {named_test_file}",
                    f"- Allowed target: {named_test_file}",
                ]
            )
        else:
            test_constraints.append("- Allowed targets: tests/**")
        test_constraints.append("- Max deletions: 0")
        if target_file:
            test_constraints.extend(
                [
                    f"- Modify only this file: {target_file}",
                    "- Do not touch any other files.",
                ]
            )
    elif task_type == "implementation_with_tests":
        test_constraints = [
            "Implementation-with-tests guidance:",
            "- Create or modify only the planned files.",
            "- Do not rewrite unrelated tests.",
            "- Prefer small diffs.",
            "- If creating a new module, include the module file and its tests.",
            "- Do not place helper tests in tests/test_cli.py unless explicitly requested.",
            "- Ensure unified diff hunk line counts match hunk headers.",
        ]
        allowed_targets = patch_plan.get("allowed_targets", [])
        if isinstance(allowed_targets, list) and allowed_targets:
            test_constraints.append(f"- Allowed targets: {', '.join(str(item) for item in allowed_targets)}")
    if _is_docs_task(task, patch_plan):
        docs_constraints = [
            "Documentation-task guidance:",
            "- Return ONLY a valid unified diff.",
            "- Target README.md.",
            "- Do not output explanation.",
            "- Do not modify source or tests unless explicitly requested.",
            "- Ensure the diff uses unified git format.",
            "- Use headers:",
            "  diff --git a/README.md b/README.md",
            "  --- a/README.md",
            "  +++ b/README.md",
            "- If README.md does not exist, use:",
            "  --- /dev/null",
            "  +++ b/README.md",
        ]
        test_constraints.extend(docs_constraints)
        if not any("Return ONLY a valid unified diff" in item for item in regen_constraints):
            regen_constraints.append("- Return ONLY a valid unified diff.")
        if not any("Modify README.md" in item for item in regen_constraints):
            regen_constraints.append("- Modify README.md.")
        if not any("Do not output explanation" in item for item in regen_constraints):
            regen_constraints.append("- Do not output explanation.")
    allowed_targets = patch_plan.get("allowed_targets", [])
    if isinstance(allowed_targets, list) and allowed_targets:
        test_constraints.extend(
            [
                "Allowed-target guidance:",
                f"- Modify only these files: {', '.join(str(item) for item in allowed_targets)}",
                "- Do not modify files outside allowed targets.",
            ]
        )
    prompt_context: dict[str, Any] = context
    if task_type == "test_generation":
        prompt_context = _shape_test_generation_context(task=task, context=context, patch_plan=patch_plan)
    return (
        "You generate a unified git diff only.\n"
        "Do not output markdown fences or explanations.\n"
        "If unsure, output an empty string.\n\n"
        f"Task: {task}\n"
        f"Failures: {failures}\n"
        f"Context: {prompt_context}\n"
        f"Patch plan: {patch_plan}\n"
        f"Aegis execution guidance: {aegis_execution}\n"
        + ("\n".join(test_constraints) + "\n" if test_constraints else "")
        + ("Regeneration constraints:\n" + "\n".join(regen_constraints) + "\n" if regen_constraints else "")
    )


def is_plausible_diff(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    if "```" in value:
        return False
    markers = ("diff --git", "--- ", "+++ ", "@@")
    return any(marker in value for marker in markers)
