from __future__ import annotations

from typing import Any


def build_replace_symbol_prompt(
    *,
    task: str,
    target_path: str,
    symbol: str,
    failure_context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> str:
    return (
        "Return strict JSON only. No markdown. No prose.\n"
        "Schema:\n"
        "{\n"
        '  "content": "replacement symbol source"\n'
        "}\n"
        "Rules:\n"
        f"- target path: {target_path}\n"
        f"- replace symbol name: {symbol}\n"
        "- return replacement symbol source only, not full file content\n"
        "- do not return unified diff\n"
        "- do not include any fields other than content\n"
        "- do not include explanation text\n"
        "- preserve behavior outside the requested symbol\n"
        f"Task: {task}\n"
        f"Context: {failure_context}\n"
        f"Patch plan: {patch_plan}\n"
    )
