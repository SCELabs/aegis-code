from __future__ import annotations

import hashlib
from typing import Any


def normalize_failure_line(line: str) -> str:
    return str(line).strip()


def normalize_failure_output(text: str) -> str:
    return "\n".join(
        normalize_failure_line(line) for line in str(text or "").splitlines() if normalize_failure_line(line)
    )


def build_failure_signature(result: Any) -> str:
    full_output = str(getattr(result, "full_output", "") or "")
    if not full_output:
        stdout = str(getattr(result, "stdout", "") or "")
        stderr = str(getattr(result, "stderr", "") or "")
        full_output = f"{stdout}\n{stderr}"
    normalized = normalize_failure_output(full_output)
    if not normalized:
        normalized = f"status={getattr(result, 'status', '')};exit={getattr(result, 'exit_code', '')}"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
