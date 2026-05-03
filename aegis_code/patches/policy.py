from __future__ import annotations

import re
from typing import Any

PLACEHOLDER_MARKERS = (
    "[...truncated...]",
    "...truncated...",
    "<truncated>",
    "[truncated]",
    "TODO: existing content",
    "# existing content",
    "# rest of file",
    "... rest of file ...",
    "... existing code ...",
)


def _task_intent_tokens(task_text: str) -> set[str]:
    stop = {
        "add",
        "tests",
        "test",
        "for",
        "the",
        "only",
        "existing",
        "behavior",
        "do",
        "not",
        "modify",
        "source",
        "files",
        "and",
        "with",
        "aegis",
        "code",
    }
    tokens = re.findall(r"[a-zA-Z_]{4,}", str(task_text or "").lower())
    return {tok for tok in tokens if tok not in stop}


def hard_invalid_content_reason(
    *,
    diff_text: str,
    validation: dict[str, Any],
    test_task: bool,
    task_text: str,
) -> str | None:
    text = str(diff_text or "")
    if not text:
        return None
    lowered = text.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker.lower() in lowered:
            return "placeholder_content"

    if not test_task:
        files = validation.get("files", []) if isinstance(validation, dict) else []
        for item in files if isinstance(files, list) else []:
            if not isinstance(item, dict):
                continue
            target = str(item.get("new_path") or item.get("old_path") or "").lower()
            if not target:
                continue
            is_docs = (
                target == "readme.md"
                or target.endswith(".md")
                or target.startswith("docs/")
            )
            if not is_docs:
                continue
            file_additions = int(item.get("additions", 0) or 0)
            file_deletions = int(item.get("deletions", 0) or 0)
            if file_deletions > 200:
                return "destructive_docs_rewrite"
            if file_deletions > 80 and file_additions < (file_deletions / 2):
                return "destructive_docs_rewrite"
        return None

    files = validation.get("files", []) if isinstance(validation, dict) else []
    additions_total = int((validation.get("summary", {}) or {}).get("additions", 0)) if isinstance(validation, dict) else 0
    deletions_total = int((validation.get("summary", {}) or {}).get("deletions", 0)) if isinstance(validation, dict) else 0
    if deletions_total > additions_total * 2 and deletions_total > 20:
        return "destructive_test_rewrite"

    intent_tokens = _task_intent_tokens(task_text)
    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("new_path") or item.get("old_path") or "")
        if not target.startswith("tests/") or not target.endswith(".py"):
            continue
        file_deletions = int(item.get("deletions", 0) or 0)
        if file_deletions > 40:
            return "destructive_test_rewrite"

    removed_symbols: list[str] = []
    for raw_line in text.splitlines():
        if raw_line.startswith("--- ") or raw_line.startswith("diff --git ") or raw_line.startswith("@@ "):
            continue
        if not raw_line.startswith("-"):
            continue
        line = raw_line[1:].strip()
        if line.startswith("import ") or line.startswith("from ") or line.startswith("class ") or line.startswith("def test_"):
            removed_symbols.append(line.lower())
    if removed_symbols:
        if not intent_tokens:
            return "destructive_test_rewrite"
        symbol_tokens = set()
        for line in removed_symbols:
            symbol_tokens.update(re.findall(r"[a-zA-Z_]{4,}", line))
        if symbol_tokens and not (symbol_tokens & intent_tokens):
            return "destructive_test_rewrite"
    return None


def hard_invalid_reason(
    *,
    syntactic_valid: bool | None,
    additions: int,
    size_threshold: int,
    plan_consistent: bool,
    diff_text: str = "",
    validation: dict[str, Any] | None = None,
    test_task: bool = False,
    task_text: str = "",
) -> str | None:
    content_reason = hard_invalid_content_reason(
        diff_text=diff_text,
        validation=validation or {},
        test_task=test_task,
        task_text=task_text,
    )
    if content_reason:
        return content_reason
    if syntactic_valid is False:
        return "syntactic_invalid"
    if additions > size_threshold:
        return "excessive_diff_size"
    if not plan_consistent:
        return "plan_inconsistent"
    return None
