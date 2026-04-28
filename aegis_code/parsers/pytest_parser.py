from __future__ import annotations

import re
from typing import Any


_SUMMARY_LINE_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.+))?$")
_TRACE_LINE_RE = re.compile(r"^(?P<file>.+?\.py):(?P<line>\d+):\s*(?P<error>.*)$")


def _norm_path(path: str) -> str:
    return path.replace("\\", "/")


def _error_nearby(lines: list[str], start_index: int) -> str:
    window_end = min(start_index + 8, len(lines))
    for idx in range(start_index, window_end):
        line = lines[idx].strip()
        if line.startswith("E   "):
            return line[4:].strip()
    return ""


def parse_pytest_output(output: str) -> dict[str, Any]:
    lines = output.splitlines()
    failed_tests: list[dict[str, Any]] = []

    for line in lines:
        match = _SUMMARY_LINE_RE.match(line.strip())
        if not match:
            continue

        nodeid = match.group(2)
        error = (match.group(3) or "").strip()
        file_path = nodeid.split("::", 1)[0]
        failed_tests.append(
            {
                "test_name": nodeid,
                "file": file_path,
                "error": error,
                "line": None,
            }
        )

    if not failed_tests:
        return {"failed_tests": [], "failure_count": 0}

    for index, line in enumerate(lines):
        trace_match = _TRACE_LINE_RE.match(line.strip())
        if not trace_match:
            continue

        trace_file = _norm_path(trace_match.group("file"))
        trace_line = int(trace_match.group("line"))
        trace_error = trace_match.group("error").strip()

        for failure in failed_tests:
            if _norm_path(failure["file"]) != trace_file:
                continue
            if failure["line"] is None:
                failure["line"] = trace_line
            if not failure["error"]:
                failure["error"] = trace_error or _error_nearby(lines, index + 1)
            break

    for failure in failed_tests:
        if not failure["error"]:
            failure["error"] = "Unknown pytest failure"

    return {"failed_tests": failed_tests, "failure_count": len(failed_tests)}

