from __future__ import annotations

import re
from typing import Any


_SUMMARY_LINE_RE = re.compile(r"^(FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.+))?$")
_TRACE_LINE_RE = re.compile(r"^(?P<file>.+?\.py):(?P<line>\d+):\s*(?P<error>.*)$")
_NODEID_RE = re.compile(r"(?P<nodeid>[^\s]+\.py::[^\s]+)")
_TRACEBACK_FILE_RE = re.compile(
    r'^\s*File\s+"(?P<file>.+?\.py)",\s+line\s+(?P<line>\d+),\s+in\s+(?P<test>[^\s]+)'
)


def _norm_path(path: str) -> str:
    return path.replace("\\", "/")


def _error_nearby(lines: list[str], start_index: int) -> str:
    window_end = min(start_index + 20, len(lines))
    collected: list[str] = []
    for idx in range(start_index, window_end):
        line = lines[idx].strip()
        if line.startswith("E   "):
            collected.append(line[4:].strip())
        elif collected and not line:
            break
    return " | ".join(part for part in collected if part)


def _add_failure(
    failures: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    nodeid: str,
    error: str,
) -> None:
    file_path = nodeid.split("::", 1)[0]
    key = (_norm_path(nodeid), _norm_path(file_path))
    if key in seen:
        return
    seen.add(key)
    failures.append(
        {
            "test_name": nodeid,
            "file": file_path,
            "error": error.strip(),
            "line": None,
        }
    )


def parse_pytest_output(output: str) -> dict[str, Any]:
    if not isinstance(output, str) or not output.strip():
        return {"failed_tests": [], "failure_count": 0}

    lines = output.splitlines()
    failed_tests: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    in_short_summary = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if "short test summary info" in line.lower():
            in_short_summary = True
            continue
        if in_short_summary and line.startswith("="):
            in_short_summary = False

        match = _SUMMARY_LINE_RE.match(line)
        if not match:
            if in_short_summary:
                nodeid_match = _NODEID_RE.search(line)
                if nodeid_match:
                    nodeid = nodeid_match.group("nodeid")
                    error = ""
                    if " - " in line:
                        error = line.split(" - ", 1)[1].strip()
                    _add_failure(failed_tests, seen, nodeid, error)
            continue

        nodeid = match.group(2)
        error = (match.group(3) or "").strip()
        _add_failure(failed_tests, seen, nodeid, error)

    if not failed_tests:
        nodeid_match = _NODEID_RE.search(output)
        if nodeid_match:
            nodeid = nodeid_match.group("nodeid")
            _add_failure(failed_tests, seen, nodeid, "")
        if not failed_tests:
            return {"failed_tests": [], "failure_count": 0}

    file_to_failure_indexes: dict[str, list[int]] = {}
    for idx, failure in enumerate(failed_tests):
        file_to_failure_indexes.setdefault(_norm_path(failure["file"]), []).append(idx)

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        trace_match = _TRACE_LINE_RE.match(line)
        if not trace_match:
            continue

        trace_file = _norm_path(trace_match.group("file"))
        trace_line = int(trace_match.group("line"))
        trace_error = trace_match.group("error").strip()
        targets = file_to_failure_indexes.get(trace_file, [])
        if not targets:
            continue

        target_index = targets[0]
        failure = failed_tests[target_index]
        if failure["line"] is None:
            failure["line"] = trace_line
        if not failure["error"]:
            failure["error"] = trace_error or _error_nearby(lines, index + 1)

    for raw_line in lines:
        tb_match = _TRACEBACK_FILE_RE.match(raw_line)
        if not tb_match:
            continue
        tb_file = _norm_path(tb_match.group("file"))
        tb_line = int(tb_match.group("line"))
        for failure in failed_tests:
            if _norm_path(failure["file"]) != tb_file:
                continue
            if failure["line"] is None:
                failure["line"] = tb_line
            break

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line.startswith("E   "):
            continue
        message = line[4:].strip()
        if not message:
            continue
        for failure in failed_tests:
            if not failure["error"]:
                failure["error"] = message or _error_nearby(lines, index)
                break

    for failure in failed_tests:
        if failure["line"] is None:
            trace_hint = re.search(r":(?P<line>\d+):", failure["error"])
            if trace_hint:
                failure["line"] = int(trace_hint.group("line"))
        if not failure["error"]:
            failure["error"] = "Unknown pytest failure"

    unique_failures = [f for f in failed_tests if str(f.get("test_name", "")).strip()]
    if not unique_failures:
        return {"failed_tests": [], "failure_count": 0}
    return {"failed_tests": unique_failures, "failure_count": len(unique_failures)}
