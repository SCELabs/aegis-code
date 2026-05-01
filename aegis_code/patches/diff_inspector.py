from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any

_HUNK_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
)


def _norm(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return str(PurePosixPath(value))


def _is_generated_or_cache(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    generated_markers = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".aegis",
    }
    if bool(parts & generated_markers):
        return True
    return any(part.endswith(".egg-info") for part in parts)


def _has_parent_traversal(path: str) -> bool:
    return ".." in PurePosixPath(path).parts


def _is_absolute_like(path: str) -> bool:
    p = PurePosixPath(path)
    if p.is_absolute():
        return True
    # Windows-like path forms after slash-normalization, e.g. C:/...
    return len(path) >= 3 and path[1:3] == ":/"


def inspect_diff(diff: str, cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    text = str(diff or "")
    warnings: list[str] = []
    errors: list[str] = []

    if not text.strip():
        return {
            "valid": False,
            "files": [],
            "summary": {"file_count": 0, "hunk_count": 0, "additions": 0, "deletions": 0},
            "warnings": [],
            "errors": ["empty_diff"],
        }

    lines = text.splitlines()
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_hunk = False
    hunk_old_expected = 0
    hunk_new_expected = 0
    hunk_old_seen = 0
    hunk_new_seen = 0

    def _finalize_hunk_if_open() -> None:
        nonlocal in_hunk
        nonlocal hunk_old_expected, hunk_new_expected, hunk_old_seen, hunk_new_seen
        if not in_hunk:
            return
        if hunk_old_seen != hunk_old_expected or hunk_new_seen != hunk_new_expected:
            errors.append("hunk_count_mismatch")
        in_hunk = False
        hunk_old_expected = 0
        hunk_new_expected = 0
        hunk_old_seen = 0
        hunk_new_seen = 0

    def _finalize_current() -> None:
        nonlocal current
        if current is None:
            return
        _finalize_hunk_if_open()
        old_path = current.get("old_path")
        new_path = current.get("new_path")
        candidate = new_path or old_path
        exists = False
        if candidate:
            check_path = root / candidate
            exists = check_path.exists()
            if not exists:
                warnings.append(f"referenced file missing: {candidate}")
            if _is_absolute_like(candidate):
                warnings.append(f"unsafe_absolute_path: {candidate}")
            if _has_parent_traversal(candidate):
                warnings.append(f"unsafe_parent_traversal: {candidate}")
            if _is_generated_or_cache(candidate):
                warnings.append(f"internal_or_generated_path: {candidate}")
        current["exists"] = exists
        files.append(current)
        current = None

    for line in lines:
        if line.startswith("diff --git "):
            _finalize_current()
            tokens = line.split()
            if len(tokens) >= 4:
                current = {
                    "old_path": _norm(tokens[2]),
                    "new_path": _norm(tokens[3]),
                    "exists": False,
                    "hunk_count": 0,
                    "additions": 0,
                    "deletions": 0,
                }
            else:
                errors.append("malformed_diff_header")
                current = {
                    "old_path": None,
                    "new_path": None,
                    "exists": False,
                    "hunk_count": 0,
                    "additions": 0,
                    "deletions": 0,
                }
            continue

        if current is None:
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            _finalize_hunk_if_open()
            current["hunk_count"] += 1
            in_hunk = True
            hunk_old_expected = int(hunk_match.group("old_count") or "1")
            hunk_new_expected = int(hunk_match.group("new_count") or "1")
            hunk_old_seen = 0
            hunk_new_seen = 0
            continue
        if line.startswith("@@"):
            _finalize_hunk_if_open()
            errors.append("malformed_hunk_header")
            continue

        if line.startswith("--- "):
            _finalize_hunk_if_open()
            path = line[4:].strip()
            current["old_path"] = None if path == "/dev/null" else _norm(path)
            continue
        if line.startswith("+++ "):
            _finalize_hunk_if_open()
            path = line[4:].strip()
            current["new_path"] = None if path == "/dev/null" else _norm(path)
            continue
        if in_hunk and line.startswith(" ") and not line.startswith("+++ "):
            hunk_old_seen += 1
            hunk_new_seen += 1
            continue
        if in_hunk and line.startswith("-") and not line.startswith("--- "):
            hunk_old_seen += 1
            current["deletions"] += 1
            continue
        if in_hunk and line.startswith("+") and not line.startswith("+++ "):
            hunk_new_seen += 1
            current["additions"] += 1
            continue
        if in_hunk and line.startswith("\\ No newline"):
            continue
        if in_hunk and line:
            _finalize_hunk_if_open()
            continue

    _finalize_current()

    if not files:
        errors.append("no_file_targets")
    targets: list[str] = []
    for item in files:
        candidate = item.get("new_path") or item.get("old_path")
        if isinstance(candidate, str) and candidate:
            targets.append(candidate)
    if len(set(targets)) != len(targets):
        errors.append("duplicate_file_targets")
    total_hunks = sum(int(item["hunk_count"]) for item in files)
    total_additions = sum(int(item["additions"]) for item in files)
    total_deletions = sum(int(item["deletions"]) for item in files)

    changed_lines = total_additions + total_deletions
    if changed_lines > 1000:
        warnings.append("very_large_diff")
    lower_text = text.lower()
    if (
        "binary files differ" in lower_text
        or "git binary patch" in lower_text
        or ("binary files" in lower_text and " differ" in lower_text)
    ):
        warnings.append("binary_diff_detected")
    if files and total_hunks == 0:
        errors.append("no_hunks")
    if any(item["hunk_count"] == 0 and (item["additions"] + item["deletions"] > 0) for item in files):
        warnings.append("malformed_hunks")

    valid = not errors
    return {
        "valid": valid,
        "files": files,
        "summary": {
            "file_count": len(files),
            "hunk_count": total_hunks,
            "additions": total_additions,
            "deletions": total_deletions,
        },
        "warnings": sorted(set(warnings)),
        "errors": sorted(set(errors)),
    }
