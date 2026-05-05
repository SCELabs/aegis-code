from __future__ import annotations

import re
from typing import Any

_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


def _norm(path: str) -> str:
    value = path.strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value


def parse_apply_diff(diff_text: str) -> tuple[list[dict[str, Any]], list[str]]:
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
