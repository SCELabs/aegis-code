from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path

from aegis_code.operations.errors import (
    INSERT_OUTPUT_INVALID,
    OPERATION_ANCHOR_AMBIGUOUS,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_VALIDATION_FAILED,
)
from aegis_code.patches.diff_inspector import inspect_diff


def _parse_insert_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, INSERT_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, INSERT_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, INSERT_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, INSERT_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, INSERT_OUTPUT_INVALID
    normalized = content if content.endswith("\n") else f"{content}\n"
    if not normalized.strip():
        return False, None, INSERT_OUTPUT_INVALID
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, INSERT_OUTPUT_INVALID
    return True, normalized, None


def _insert_after_anchor(*, original_text: str, anchor: str, insert_content: str) -> tuple[bool, str | None, str | None]:
    ok, index, error = resolve_insert_after_index(original_text=original_text, anchor=anchor)
    if not ok or index is None:
        return False, None, error
    new_text = insert_after_index(original_text=original_text, index=index, insert_content=insert_content)
    return True, new_text, None


def resolve_insert_after_index(*, original_text: str, anchor: str) -> tuple[bool, int | None, str | None]:
    lines = str(original_text or "").splitlines(keepends=True)
    needle = str(anchor or "").strip()
    matches = [idx for idx, line in enumerate(lines) if str(line).rstrip("\n\r").strip() == needle]
    if not matches:
        return False, None, OPERATION_ANCHOR_NOT_FOUND
    if len(matches) != 1:
        return False, None, OPERATION_ANCHOR_AMBIGUOUS
    return True, int(matches[0]), None


def insert_after_index(*, original_text: str, index: int, insert_content: str) -> str:
    lines = str(original_text or "").splitlines(keepends=True)
    idx = int(index)
    insertion = str(insert_content or "")
    new_lines = lines[: idx + 1] + [insertion] + lines[idx + 1 :]
    return "".join(new_lines)


def _build_insert_after_diff(*, target_path: str, original_text: str, new_text: str) -> str:
    old_lines = str(original_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _validate_insert_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, OPERATION_VALIDATION_FAILED
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) != 0:
        return False, OPERATION_VALIDATION_FAILED
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, OPERATION_VALIDATION_FAILED
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    new_path = str(file_entry.get("new_path", "") or "")
    if new_path != target_path:
        return False, OPERATION_VALIDATION_FAILED
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    return True, None
