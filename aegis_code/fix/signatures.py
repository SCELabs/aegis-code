from __future__ import annotations

import hashlib
import re
from typing import Any

from aegis_code.parsers.pytest_parser import parse_pytest_output

_NODEID_RE = re.compile(r"([^\s]+\.py::[^\s]+)")
_TIMING_RE = re.compile(r"=+\s*[\d\s\w,./%-]*in\s+\d+(\.\d+)?s\s*=+", re.IGNORECASE)
_CARET_RE = re.compile(r"^\s*\^+\s*$")
_LINE_NUMBER_RE = re.compile(r":\d+")


def normalize_failure_line(line: str) -> str:
    text = str(line or "").replace("\\", "/").strip()
    if not text:
        return ""
    if _CARET_RE.match(text):
        return ""
    if _TIMING_RE.search(text):
        return ""
    if text.startswith("===") and "seconds" in text.lower():
        return ""
    if text.startswith("FAILED ") or text.startswith("ERROR "):
        text = _LINE_NUMBER_RE.sub("", text)
    if text.startswith("File ") and ", line " in text:
        text = re.sub(r", line \d+", "", text)
    return " ".join(text.split())


def normalize_failure_output(text: str) -> str:
    return "\n".join(
        normalize_failure_line(line) for line in str(text or "").splitlines() if normalize_failure_line(line)
    )


def _normalize_failure_error(error: str) -> tuple[str, str]:
    text = str(error or "").replace("\\", "/")
    text = re.sub(r"\s+", " ", text).strip()
    text = _LINE_NUMBER_RE.sub("", text)
    exc_type = ""
    exc_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*Error)\b", text)
    if exc_match:
        exc_type = exc_match.group(1)
    essence = text
    if exc_type:
        essence = text.replace(exc_type, "", 1).strip(" :|-")
    essence = re.sub(r"\s+", " ", essence).strip()
    return exc_type, essence


def _signature_from_parsed_failures(full_output: str) -> str | None:
    parsed = parse_pytest_output(full_output)
    failures = parsed.get("failed_tests", []) if isinstance(parsed, dict) else []
    if not isinstance(failures, list) or not failures:
        return None
    items: list[str] = []
    for failure in failures:
        if not isinstance(failure, dict):
            continue
        nodeid = str(failure.get("test_name", "") or "").replace("\\", "/").strip()
        file_path = str(failure.get("file", "") or "").replace("\\", "/").strip()
        error = str(failure.get("error", "") or "")
        exc_type, essence = _normalize_failure_error(error)
        if not nodeid:
            continue
        items.append(f"node={nodeid}|file={file_path}|exc={exc_type}|essence={essence}")
    if not items:
        return None
    payload = "\n".join(sorted(items))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_failure_signature(result: Any) -> str:
    full_output = str(getattr(result, "full_output", "") or "")
    if not full_output:
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        full_output = f"{stdout}\n{stderr}"
    parsed_signature = _signature_from_parsed_failures(full_output)
    if parsed_signature:
        return parsed_signature
    normalized = normalize_failure_output(full_output)
    if normalized:
        nodeids = sorted(set(match.group(1).replace("\\", "/") for match in _NODEID_RE.finditer(normalized)))
        if nodeids:
            normalized = "\n".join(nodeids + [normalized])
    if not normalized:
        normalized = f"status={getattr(result, 'status', '')};exit={getattr(result, 'exit_code', '')}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
