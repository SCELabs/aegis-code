from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any


_DIFF_GIT_RE = re.compile(r"^diff --git a/(?P<a>\S+) b/(?P<b>\S+)$")
_FILE_LINE_RE = re.compile(r"^(---|\+\+\+) (?P<path>\S+)$")


def _norm(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    if cleaned.startswith("a/") or cleaned.startswith("b/"):
        cleaned = cleaned[2:]
    return str(PurePosixPath(cleaned))


def _extract_diff_targets(diff: str) -> set[str]:
    targets: set[str] = set()
    for raw in diff.splitlines():
        line = raw.strip()
        git_match = _DIFF_GIT_RE.match(line)
        if git_match:
            targets.add(_norm(git_match.group("a")))
            targets.add(_norm(git_match.group("b")))
            continue
        file_match = _FILE_LINE_RE.match(line)
        if not file_match:
            continue
        path = file_match.group("path")
        if path == "/dev/null":
            continue
        targets.add(_norm(path))
    return {target for target in targets if target and target != "."}


def _extract_new_file_targets(diff: str) -> set[str]:
    targets: set[str] = set()
    old_path: str | None = None
    for raw in diff.splitlines():
        line = raw.strip()
        file_match = _FILE_LINE_RE.match(line)
        if not file_match:
            continue
        marker = line[:3]
        path = file_match.group("path")
        if marker == "---":
            old_path = path
            continue
        if marker == "+++":
            new_path = path
            if old_path == "/dev/null" and new_path != "/dev/null":
                targets.add(_norm(new_path))
            old_path = None
    return {target for target in targets if target and target != "."}


def _mapped_source_files(
    failure_files: set[str],
    context_files: set[str],
) -> set[str]:
    mapped: set[str] = set()
    for failure in failure_files:
        failure_path = PurePosixPath(failure)
        name = failure_path.name
        if not (name.startswith("test_") and name.endswith(".py")):
            continue
        source_name = name[len("test_") :]
        for context_path in context_files:
            cpath = PurePosixPath(context_path)
            if cpath.name == source_name and "tests" not in cpath.parts:
                mapped.add(context_path)
    return mapped


def evaluate_diff(
    diff: str,
    failures: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    issues: list[str] = []
    text = str(diff or "").strip()
    if not text:
        issues.append("empty_diff")
        return {
            "grounded": False,
            "relevant_files": False,
            "confidence": 0.3,
            "issues": issues,
        }

    targets = _extract_diff_targets(text)
    new_file_targets = _extract_new_file_targets(text)
    has_diff_markers = any(marker in text for marker in ("diff --git", "--- ", "+++ ", "@@"))
    if not has_diff_markers:
        issues.append("invalid_format")

    failure_files = {
        _norm(str(item.get("file", "")))
        for item in failures.get("failed_tests", [])
        if isinstance(item, dict) and str(item.get("file", "")).strip()
    }
    context_files = {
        _norm(str(item.get("path", "")))
        for item in context.get("files", [])
        if isinstance(item, dict) and str(item.get("path", "")).strip()
    }
    known_files = failure_files | context_files

    if not targets:
        issues.append("no_file_targets")
        grounded = False
    elif known_files and not (targets - known_files).issubset(new_file_targets):
        issues.append("no_file_targets")
        grounded = False
    else:
        grounded = True

    relevant_set = failure_files | _mapped_source_files(failure_files, context_files)
    relevant_files = bool(targets & relevant_set)
    if targets and not relevant_files:
        issues.append("unrelated_files")

    confidence = 0.5
    if grounded:
        confidence += 0.2
    if relevant_files:
        confidence += 0.2
    if issues:
        confidence -= 0.2
    confidence = max(0.0, min(1.0, round(confidence, 3)))

    return {
        "grounded": grounded,
        "relevant_files": relevant_files,
        "confidence": confidence,
        "issues": issues,
    }
