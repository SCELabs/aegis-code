from __future__ import annotations

from typing import Any


def build_create_file_prompt(
    *,
    task: str,
    target_path: str,
    failure_context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> str:
    return (
        "Return strict JSON only. No markdown. No prose.\n"
        "Schema:\n"
        "{\n"
        '  "content": "full file content"\n'
        "}\n"
        "Rules:\n"
        f"- target path: {target_path}\n"
        "- return full file content for the new file only\n"
        "- do not return unified diff\n"
        "- do not include any fields other than content\n"
        "- do not include explanation text\n"
        f"Task: {task}\n"
        f"Context: {failure_context}\n"
        f"Patch plan: {patch_plan}\n"
    )
