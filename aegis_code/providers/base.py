from __future__ import annotations

from typing import Any


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
    raw_regen = patch_plan.get("regeneration_constraints", [])
    if isinstance(raw_regen, list):
        regen_constraints = [f"- {str(item)}" for item in raw_regen if str(item).strip()]
    if task_type == "test_generation":
        test_constraints = [
            "Test-generation guidance:",
            "- Prefer modifying tests only.",
            "- Do not modify source files unless explicitly requested.",
            "- Put imports at the top of test files.",
            "- Replace placeholder tests cleanly instead of appending imports after functions.",
            "- Keep diff hunks minimal and valid.",
            "- Ensure unified diff hunk line counts match hunk headers.",
        ]
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
