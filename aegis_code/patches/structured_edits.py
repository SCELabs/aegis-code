from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import Any

from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.diff_normalizer import normalize_unified_diff


_WINDOWS_ABS_RE = re.compile(r"^[A-Za-z]:[\\/]")
_BANNED_PARTS = {".git", ".aegis", "venv", ".venv", "__pycache__"}


def parse_structured_edit_response(text: str) -> dict:
    raw = str(text or "").strip()
    try:
        data = json.loads(raw)
    except Exception:
        return {"ok": False, "errors": ["invalid_json"], "edits": {"changes": []}}
    if not isinstance(data, dict):
        return {"ok": False, "errors": ["invalid_json_root"], "edits": {"changes": []}}
    changes = data.get("changes", [])
    if not isinstance(changes, list):
        return {"ok": False, "errors": ["invalid_changes"], "edits": {"changes": []}}
    return {"ok": True, "errors": [], "edits": {"changes": changes}}


def _is_binary_like(content: str) -> bool:
    value = str(content or "")
    if "\x00" in value:
        return True
    total = len(value)
    if total == 0:
        return False
    non_text = sum(1 for ch in value if ord(ch) < 9 or (13 < ord(ch) < 32))
    return (non_text / max(1, total)) > 0.10


def _safe_rel_path(path_text: str, cwd: Path, allowed_targets: set[str] | None) -> tuple[str | None, str | None]:
    raw = str(path_text or "").strip().replace("\\", "/")
    if not raw:
        return None, "empty_path"
    if raw.startswith("/") or _WINDOWS_ABS_RE.match(raw):
        return None, "absolute_path"
    rel = Path(raw)
    if rel.is_absolute():
        return None, "absolute_path"
    if ".." in rel.parts:
        return None, "parent_traversal"
    if any(part in _BANNED_PARTS for part in rel.parts):
        return None, "banned_path"
    resolved = (cwd / rel).resolve()
    try:
        resolved.relative_to(cwd.resolve())
    except Exception:
        return None, "outside_root"
    normalized = rel.as_posix()
    if allowed_targets is not None and normalized not in allowed_targets:
        return None, "outside_allowed_targets"
    return normalized, None


def structured_edits_to_diff(edits: dict, cwd: Path, allowed_targets: list[str] | None = None) -> dict:
    changes = edits.get("changes", []) if isinstance(edits, dict) else []
    if not isinstance(changes, list):
        return {"ok": False, "diff": "", "errors": ["invalid_changes"], "warnings": [], "files": []}
    allowed_set = {str(item).strip().replace("\\", "/") for item in (allowed_targets or []) if str(item).strip()} if allowed_targets else None
    chunks: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    files: list[str] = []
    root = cwd.resolve()

    for item in changes:
        if not isinstance(item, dict):
            errors.append("invalid_change")
            continue
        path_value, path_error = _safe_rel_path(str(item.get("path", "") or ""), root, allowed_set)
        if path_error is not None:
            errors.append(f"invalid_path:{path_error}")
            continue
        mode = str(item.get("mode", "") or "").strip().lower()
        content = item.get("content", "")
        if not isinstance(content, str):
            errors.append("invalid_content")
            continue
        if _is_binary_like(content):
            errors.append("binary_content")
            continue
        target = (root / path_value).resolve()
        new_text = content if content.endswith("\n") else content + "\n"
        files.append(path_value)

        if mode == "replace":
            if not target.exists() or not target.is_file():
                errors.append("replace_target_missing")
                continue
            old_text = target.read_text(encoding="utf-8", errors="replace")
            old_lines = old_text.splitlines()
            new_lines = new_text.splitlines()
            body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{path_value}", tofile=f"b/{path_value}", lineterm=""))
            if not body:
                warnings.append(f"no_changes:{path_value}")
                continue
            chunk = f"diff --git a/{path_value} b/{path_value}\n" + "\n".join(body) + "\n"
            chunks.append(chunk)
        elif mode == "create":
            if target.exists():
                errors.append("create_target_exists")
                continue
            new_lines = new_text.splitlines()
            body = list(unified_diff([], new_lines, fromfile="/dev/null", tofile=f"b/{path_value}", lineterm=""))
            chunk = f"diff --git a/{path_value} b/{path_value}\n" + "\n".join(body) + "\n"
            chunks.append(chunk)
        else:
            errors.append("unsupported_mode")

    if errors:
        return {"ok": False, "diff": "", "errors": errors, "warnings": warnings, "files": files}
    diff_text = normalize_unified_diff("".join(chunks).strip())
    if not diff_text:
        return {"ok": False, "diff": "", "errors": ["empty_diff"], "warnings": warnings, "files": files}
    checked = check_patch_text(diff_text, cwd=root)
    if bool(checked.get("apply_blocked", False)):
        return {"ok": False, "diff": "", "errors": ["invalid_diff"], "warnings": warnings, "files": files}
    return {"ok": True, "diff": diff_text, "errors": [], "warnings": warnings, "files": files}
