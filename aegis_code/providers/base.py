from __future__ import annotations

from typing import Any


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
    if max_chars <= 0:
        return {"files": []}
    files = context.get("files", [])
    if not isinstance(files, list):
        return {"files": []}
    trimmed: list[dict[str, str]] = []
    remaining = max_chars
    for item in files:
        path = str(item.get("path", ""))
        content = str(item.get("content", ""))
        if not path:
            continue
        chunk = content[:remaining]
        trimmed.append({"path": path, "content": chunk})
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return {"files": trimmed}


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
        test_constraints = [
            "Test-generation guidance:",
            "- Produce a full-file unified diff for the test file.",
            "- Replace the entire contents of the test file.",
            "- Ensure the hunk header matches the full file length.",
            "- Return exactly one diff block.",
            "- Prefer modifying tests only.",
            "- Do not modify source files unless explicitly requested.",
            "- Put imports at the top of test files.",
            "- Replace placeholder tests cleanly instead of appending imports after functions.",
            "- Keep diff hunks minimal and valid.",
            "- Ensure unified diff hunk line counts match hunk headers.",
        ]
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
    return (
        "You generate a unified git diff only.\n"
        "Do not output markdown fences or explanations.\n"
        "If unsure, output an empty string.\n\n"
        f"Task: {task}\n"
        f"Failures: {failures}\n"
        f"Context: {context}\n"
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
