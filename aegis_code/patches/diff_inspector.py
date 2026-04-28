from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any


def _norm(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return str(PurePosixPath(value))


def _is_generated_or_cache(path: str) -> bool:
    parts = set(PurePosixPath(path).parts)
    generated_markers = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".aegis",
    }
    return bool(parts & generated_markers)


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

    def _finalize_current() -> None:
        nonlocal current
        if current is None:
            return
        old_path = current.get("old_path")
        new_path = current.get("new_path")
        candidate = new_path or old_path
        exists = False
        if candidate:
            check_path = root / candidate
            exists = check_path.exists()
            if not exists:
                warnings.append(f"referenced file missing: {candidate}")
            if _is_generated_or_cache(candidate):
                warnings.append(f"touches generated/internal path: {candidate}")
            if candidate.startswith(".aegis/"):
                warnings.append(f"touches .aegis path: {candidate}")
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

        if line.startswith("--- "):
            path = line[4:].strip()
            current["old_path"] = None if path == "/dev/null" else _norm(path)
            continue
        if line.startswith("+++ "):
            path = line[4:].strip()
            current["new_path"] = None if path == "/dev/null" else _norm(path)
            continue
        if line.startswith("@@"):
            current["hunk_count"] += 1
            continue
        if line.startswith("+") and not line.startswith("+++ "):
            current["additions"] += 1
            continue
        if line.startswith("-") and not line.startswith("--- "):
            current["deletions"] += 1
            continue

    _finalize_current()

    if not files:
        errors.append("no_file_targets")
    total_hunks = sum(int(item["hunk_count"]) for item in files)
    total_additions = sum(int(item["additions"]) for item in files)
    total_deletions = sum(int(item["deletions"]) for item in files)

    changed_lines = total_additions + total_deletions
    if changed_lines > 1000:
        warnings.append("very_large_diff")
    if "binary files differ" in text.lower() or "git binary patch" in text.lower():
        warnings.append("binary_diff_detected")
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

