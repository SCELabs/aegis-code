from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path

from aegis_code.operations.errors import CREATE_FILE_OUTPUT_INVALID, OPERATION_VALIDATION_FAILED
from aegis_code.patches.diff_inspector import inspect_diff


def _parse_create_file_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, CREATE_FILE_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, CREATE_FILE_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    normalized = content if content.endswith("\n") else f"{content}\n"
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    return True, normalized, None


def _build_create_file_diff(*, target_path: str, new_content: str) -> str:
    old_lines: list[str] = []
    new_lines = str(new_content or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile="/dev/null", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\nnew file mode 100644\n".format(target_path) + "\n".join(body) + "\n"


def _target_exists(*, cwd: Path, target_path: str) -> bool:
    return ((cwd.resolve() / str(target_path or "")).resolve()).exists()


def _validate_create_file_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
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
    old_path = file_entry.get("old_path")
    new_path = str(file_entry.get("new_path", "") or "")
    if old_path is not None:
        return False, OPERATION_VALIDATION_FAILED
    if new_path != target_path:
        return False, OPERATION_VALIDATION_FAILED
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    return True, None
