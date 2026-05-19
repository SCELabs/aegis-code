from __future__ import annotations

import json
from typing import Any, Mapping

from aegis_code.api.errors import AegisApplyError, AegisApiError, AegisPatchError

MAX_REQUEST_BYTES = 200_000
MAX_WORKSPACE_LENGTH = 1024
MAX_TASK_LENGTH = 10_000
MAX_TEXT_FIELD_LENGTH = 8_000
MAX_DIFF_PATH_LENGTH = 4096
MAX_PATCH_FILES = 200
MAX_DIFF_TEXT_BYTES = 300_000


def normalize_workspace(value: str | None) -> str:
    workspace = str(value or ".").strip() or "."
    if len(workspace) > MAX_WORKSPACE_LENGTH:
        raise AegisApiError(f"workspace path is too long (max {MAX_WORKSPACE_LENGTH} characters)")
    return workspace


def require_mapping(payload: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise AegisApiError(f"{label} must be an object")
    return payload


def validate_request_size(payload: Any, *, max_bytes: int = MAX_REQUEST_BYTES) -> None:
    try:
        encoded = json.dumps(payload, default=str).encode("utf-8")
    except Exception as exc:
        raise AegisApiError("Request payload must be JSON-serializable.") from exc
    if len(encoded) > max_bytes:
        raise AegisApiError(f"Request payload exceeds {max_bytes} bytes.")


def _validate_optional_text(value: str | None, *, field_name: str, max_length: int) -> None:
    if value is None:
        return
    if len(value) > max_length:
        raise AegisPatchError(f"{field_name} exceeds max length ({max_length}).")


def validate_patch_inputs(*, task: str, files: tuple[str, ...], anchor: str | None, symbol: str | None) -> None:
    if len(task) > MAX_TASK_LENGTH:
        raise AegisPatchError(f"task exceeds max length ({MAX_TASK_LENGTH}).")
    if len(files) > MAX_PATCH_FILES:
        raise AegisPatchError(f"files exceeds max count ({MAX_PATCH_FILES}).")
    _validate_optional_text(anchor, field_name="anchor", max_length=MAX_TEXT_FIELD_LENGTH)
    _validate_optional_text(symbol, field_name="symbol", max_length=MAX_TEXT_FIELD_LENGTH)


def validate_diff_path(diff_path: str | None) -> None:
    if diff_path is None:
        return
    if len(diff_path) > MAX_DIFF_PATH_LENGTH:
        raise AegisApplyError(f"diff_path exceeds max length ({MAX_DIFF_PATH_LENGTH}).")

