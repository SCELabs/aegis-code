from __future__ import annotations

import ast
import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import Any

from aegis_code.patches.diff_inspector import inspect_diff


def _build_append_diff(*, target_path: str, original_text: str, appended_content: str) -> str:
    append_text = str(appended_content or "")
    if append_text and not append_text.endswith("\n"):
        append_text += "\n"
    candidate = str(original_text or "") + append_text
    old_lines = str(original_text or "").splitlines()
    new_lines = candidate.splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _collect_defined_names(tree: ast.AST) -> set[str]:
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(str(node.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = str(alias.asname or alias.name.split(".")[0]).strip()
                if bound:
                    defined.add(bound)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if str(alias.name) == "*":
                    continue
                bound = str(alias.asname or alias.name).strip()
                if bound:
                    defined.add(bound)
    return defined


def _append_python_sanity_error(*, target_path: str, original_text: str, appended_content: str) -> str | None:
    if not str(target_path).endswith(".py"):
        return None
    candidate = str(original_text or "") + str(appended_content or "")
    try:
        candidate_tree = ast.parse(candidate)
    except SyntaxError:
        return "append_syntax_invalid"
    try:
        appended_tree = ast.parse(str(appended_content or ""))
    except SyntaxError:
        return "append_syntax_invalid"
    defined_names = _collect_defined_names(candidate_tree)
    builtins_names = set(dir(__import__("builtins")))
    suspicious: set[str] = set()
    for node in ast.walk(appended_tree):
        if not isinstance(node, ast.keyword):
            continue
        value = node.value
        if not isinstance(value, ast.Name) or not isinstance(value.ctx, ast.Load):
            continue
        name = str(value.id or "")
        if len(name) == 1 and name not in defined_names and name not in builtins_names:
            suspicious.add(name)
    if suspicious:
        return "append_semantic_suspicious"
    return None


def _parse_append_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, "append_output_invalid"
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, "append_output_invalid"
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, "append_output_invalid"
    if not isinstance(payload, dict):
        return False, None, "append_output_invalid"
    if "changes" in payload:
        return False, None, "append_output_invalid"
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, "append_output_invalid"
    if not content.strip():
        return True, "", None
    normalized = content if content.endswith("\n") else f"{content}\n"
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, "append_output_invalid"
    return True, normalized, None


def _validate_append_diff(*, diff_text: str, original_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    _ = original_text
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, "invalid_append_operation"
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) != 0:
        return False, "invalid_append_operation"
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, "invalid_append_operation"
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    new_path = str(file_entry.get("new_path", "") or "")
    if new_path != target_path:
        return False, "invalid_append_operation"
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, "invalid_append_operation"
    return True, None

