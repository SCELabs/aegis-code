from __future__ import annotations

from typing import Any


def build_replace_block_prompt(
    *,
    task: str,
    target_path: str,
    anchor: str,
    failure_context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> str:
    return (
        "Return strict JSON only. No markdown. No prose.\n"
        "Schema:\n"
        "{\n"
        '  "content": "replacement block content"\n'
        "}\n"
        "Rules:\n"
        f"- target path: {target_path}\n"
        f"- replace exact anchor block text: {anchor}\n"
        "- return replacement block content only, not full file content\n"
        "- do not return unified diff\n"
        "- do not include any fields other than content\n"
        "- do not include explanation text\n"
        "- preserve behavior outside the requested block\n"
        f"Task: {task}\n"
        f"Context: {failure_context}\n"
        f"Patch plan: {patch_plan}\n"
    )
