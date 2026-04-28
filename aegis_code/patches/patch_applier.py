from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aegis_code.patches.apply_check import check_patch_file

_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


def _norm(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def _parse_diff(diff_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    lines = diff_text.splitlines()
    files: list[dict[str, Any]] = []
    i = 0
    current: dict[str, Any] | None = None
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            tokens = line.split()
            if len(tokens) < 4:
                errors.append("malformed_diff_header")
                i += 1
                continue
            current = {
                "old_path": _norm(tokens[2]),
                "new_path": _norm(tokens[3]),
                "hunks": [],
                "additions": 0,
                "deletions": 0,
            }
            files.append(current)
            i += 1
            continue

        if current is None:
            i += 1
            continue

        if line.startswith("--- "):
            path = line[4:].strip()
            current["old_path"] = None if path == "/dev/null" else _norm(path)
            i += 1
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            current["new_path"] = None if path == "/dev/null" else _norm(path)
            i += 1
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            hunk = {
                "old_start": int(hunk_match.group("old_start")),
                "old_count": int(hunk_match.group("old_count") or "1"),
                "new_start": int(hunk_match.group("new_start")),
                "new_count": int(hunk_match.group("new_count") or "1"),
                "lines": [],
            }
            i += 1
            while i < len(lines):
                content = lines[i]
                if content.startswith("diff --git ") or _HUNK_RE.match(content):
                    break
                if content.startswith((" ", "-", "+")):
                    hunk["lines"].append((content[:1], content[1:]))
                    if content.startswith("+") and not content.startswith("+++"):
                        current["additions"] += 1
                    if content.startswith("-") and not content.startswith("---"):
                        current["deletions"] += 1
                elif content.startswith("\\ No newline"):
                    pass
                else:
                    errors.append("malformed_hunk_line")
                    break
                i += 1
            current["hunks"].append(hunk)
            continue

        i += 1

    if not files:
        errors.append("no_file_targets")
    return files, sorted(set(errors))


def _ensure_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _apply_hunks(source: str, hunks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    src_lines = source.splitlines()
    out: list[str] = []
    src_idx = 0
    for hunk in hunks:
        target_idx = hunk["old_start"] - 1
        if target_idx < src_idx or target_idx > len(src_lines):
            return None, "context_mismatch"
        out.extend(src_lines[src_idx:target_idx])
        src_idx = target_idx
        for kind, text in hunk["lines"]:
            if kind == " ":
                if src_idx >= len(src_lines) or src_lines[src_idx] != text:
                    return None, "context_mismatch"
                out.append(src_lines[src_idx])
                src_idx += 1
            elif kind == "-":
                if src_idx >= len(src_lines) or src_lines[src_idx] != text:
                    return None, "context_mismatch"
                src_idx += 1
            elif kind == "+":
                out.append(text)
    out.extend(src_lines[src_idx:])
    return "\n".join(out) + ("\n" if source.endswith("\n") else ""), None


def apply_patch_file(path: Path, cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    result: dict[str, Any] = {
        "applied": False,
        "path": str(path),
        "files_changed": [],
        "warnings": [],
        "errors": [],
    }

    try:
        check_result = check_patch_file(path, cwd=root)
    except FileNotFoundError:
        result["errors"] = ["diff_file_not_found"]
        return result
    except Exception as exc:
        result["errors"] = [str(exc)]
        return result

    result["warnings"] = list(check_result.get("warnings", []))
    if not check_result.get("valid", False) or check_result.get("errors"):
        result["errors"] = list(check_result.get("errors", []))
        return result

    severe_prefixes = ("unsafe_absolute_path", "unsafe_parent_traversal", "internal_or_generated_path")
    if any(str(w).startswith(severe_prefixes) for w in result["warnings"]):
        result["errors"] = ["unsafe_paths"]
        return result

    diff_text = path.read_text(encoding="utf-8")
    files, parse_errors = _parse_diff(diff_text)
    if parse_errors:
        result["errors"] = parse_errors
        return result

    plan: list[dict[str, Any]] = []
    for file_patch in files:
        old_path = file_patch.get("old_path")
        new_path = file_patch.get("new_path")
        if old_path is None or new_path is None:
            result["errors"] = ["unsupported_new_or_delete_file"]
            return result
        if old_path != new_path:
            result["errors"] = ["unsupported_rename"]
            return result

        target = root / old_path
        if not target.exists():
            result["errors"] = ["missing_target_file"]
            return result
        if not _ensure_within_root(target, root):
            result["errors"] = ["path_outside_cwd"]
            return result

        source = target.read_text(encoding="utf-8")
        updated, apply_error = _apply_hunks(source, file_patch.get("hunks", []))
        if apply_error:
            result["errors"] = [apply_error]
            return result
        assert updated is not None
        plan.append(
            {
                "path": target,
                "relative_path": old_path,
                "new_content": updated,
                "additions": int(file_patch.get("additions", 0)),
                "deletions": int(file_patch.get("deletions", 0)),
            }
        )

    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_root = root / ".aegis" / "backups" / timestamp
    written: list[dict[str, Any]] = []
    try:
        for item in plan:
            target = item["path"]
            rel = Path(str(item["relative_path"]))
            backup_path = backup_root / rel
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            backup_path.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
            target.write_text(item["new_content"], encoding="utf-8")
            changed = {
                "path": str(rel).replace("\\", "/"),
                "backup_path": str(backup_path),
                "additions": item["additions"],
                "deletions": item["deletions"],
            }
            written.append({"target": target, "backup_path": backup_path, "entry": changed})
    except Exception as exc:
        for entry in written:
            entry["target"].write_text(entry["backup_path"].read_text(encoding="utf-8"), encoding="utf-8")
        result["errors"] = [f"apply_failed: {exc}"]
        return result

    result["applied"] = True
    result["files_changed"] = [entry["entry"] for entry in written]
    return result


def format_apply_result(result: dict[str, Any]) -> str:
    lines = [
        f"Patch apply: {result.get('path')}",
        f"Applied: {result.get('applied', False)}",
        f"Files changed: {len(result.get('files_changed', []))}",
    ]
    for item in result.get("files_changed", []):
        lines.append(f"- {item.get('path')} (backup: {item.get('backup_path')})")
    lines.append("Warnings:")
    warnings = result.get("warnings", [])
    if warnings:
        lines.extend(f"- {w}" for w in warnings)
    else:
        lines.append("- none")
    lines.append("Errors:")
    errors = result.get("errors", [])
    if errors:
        lines.extend(f"- {e}" for e in errors)
    else:
        lines.append("- none")
    return "\n".join(lines)
