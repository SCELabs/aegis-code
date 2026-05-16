from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aegis_code.operations.errors import (
    OPERATION_CONTRACT_INVALID,
    OPERATION_TARGET_EXISTS,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
)
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _build_rename_file_diff(*, source_path: str, destination_path: str, original_text: str) -> str:
    lines = str(original_text or "").splitlines()
    if lines:
        hunk = (
            f"@@ -1,{len(lines)} +1,{len(lines)} @@\n"
            + "\n".join(f" {line}" for line in lines)
            + "\n"
        )
    else:
        hunk = "@@ -0,0 +0,0 @@\n"
    return (
        f"diff --git a/{source_path} b/{destination_path}\n"
        "similarity index 100%\n"
        f"rename from {source_path}\n"
        f"rename to {destination_path}\n"
        f"--- a/{source_path}\n"
        f"+++ b/{destination_path}\n"
        f"{hunk}"
    )


def _validate_rename_file_diff(
    *,
    diff_text: str,
    source_path: str,
    destination_path: str,
    cwd: Path,
) -> tuple[bool, str | None]:
    expected_from = f"rename from {source_path}"
    expected_to = f"rename to {destination_path}"
    if "similarity index 100%" not in diff_text:
        return False, OPERATION_VALIDATION_FAILED
    if expected_from not in diff_text or expected_to not in diff_text:
        return False, OPERATION_VALIDATION_FAILED
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, OPERATION_VALIDATION_FAILED
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("additions", 0) or 0) != 0 or int(summary.get("deletions", 0) or 0) != 0:
        return False, OPERATION_VALIDATION_FAILED
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, OPERATION_VALIDATION_FAILED
    item = files[0] if isinstance(files[0], dict) else {}
    if str(item.get("old_path", "") or "") != source_path:
        return False, OPERATION_VALIDATION_FAILED
    if str(item.get("new_path", "") or "") != destination_path:
        return False, OPERATION_VALIDATION_FAILED
    return True, None


def run_rename_file_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    source_path = str(request.contract.target_file or "").strip()
    destination_path = (
        str(request.contract.destination_path or "").strip()
        or str(request.destination_path or "").strip()
    )
    if not source_path or not destination_path:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=OPERATION_CONTRACT_INVALID,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if source_path == destination_path:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=OPERATION_CONTRACT_INVALID,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    source_file = (request.cwd.resolve() / source_path).resolve()
    if not source_file.exists() or not source_file.is_file():
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=OPERATION_TARGET_MISSING,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    destination_file = (request.cwd.resolve() / destination_path).resolve()
    if destination_file.exists():
        return OperationResult(
            attempted=True,
            status="blocked",
            error=OPERATION_TARGET_EXISTS,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    original_text = source_file.read_text(encoding="utf-8", errors="replace")
    diff_text = _build_rename_file_diff(
        source_path=source_path,
        destination_path=destination_path,
        original_text=original_text,
    )
    ok, err = _validate_rename_file_diff(
        diff_text=diff_text,
        source_path=source_path,
        destination_path=destination_path,
        cwd=request.cwd,
    )
    if not ok or not diff_text:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=err or OPERATION_VALIDATION_FAILED,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    return OperationResult(
        attempted=True,
        status="generated",
        diff_text=diff_text,
        error=None,
        operation=request.contract.operation,
        source=request.contract.source,
    )
