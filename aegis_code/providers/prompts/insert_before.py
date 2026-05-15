from __future__ import annotations

from typing import Any


def build_insert_before_prompt(
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
        '  "content": "text to insert"\n'
        "}\n"
        "Rules:\n"
        f"- target path: {target_path}\n"
        f"- insert before exact anchor text: {anchor}\n"
        "- return only insertion content, not full file content\n"
        "- do not include the anchor line itself in returned content\n"
        "- do not repeat surrounding existing file blocks; return only new insertion text\n"
        "- do not include any existing line from the target file near the anchor\n"
        "- do not return unified diff\n"
        "- do not include any fields other than content\n"
        f"Task: {task}\n"
        f"Context: {failure_context}\n"
        f"Patch plan: {patch_plan}\n"
    )
