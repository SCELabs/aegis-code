from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aegis_code.operations.errors import (
    OPERATION_ANCHOR_AMBIGUOUS,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_CONTRACT_INVALID,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
)
from aegis_code.operations.replace_block import (
    _build_replace_block_diff,
    _normalize_line_endings,
    replace_block_span,
    resolve_replace_block_span,
)
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _validate_delete_block_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, OPERATION_VALIDATION_FAILED
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, OPERATION_VALIDATION_FAILED
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    old_path = file_entry.get("old_path")
    new_path = file_entry.get("new_path")
    if old_path is None or new_path is None:
        return False, OPERATION_VALIDATION_FAILED
    if str(old_path) != target_path or str(new_path) != target_path:
        return False, OPERATION_VALIDATION_FAILED
    return True, None


def run_delete_block_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    target_path = str(request.contract.target_file or "").strip()
    anchor = str(request.contract.anchor or "").strip()
    if not target_path or not anchor:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=OPERATION_CONTRACT_INVALID,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    target_file = (request.cwd.resolve() / target_path).resolve()
    if not target_file.exists() or not target_file.is_file():
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=OPERATION_TARGET_MISSING,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    original_text = _normalize_line_endings(target_file.read_text(encoding="utf-8", errors="replace"))
    span_ok, span, span_error = resolve_replace_block_span(original_text=original_text, anchor=anchor)
    if not span_ok or span is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=span_error
            if span_error in {OPERATION_ANCHOR_NOT_FOUND, OPERATION_ANCHOR_AMBIGUOUS}
            else OPERATION_CONTRACT_INVALID,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    updated_text = replace_block_span(
        original_text=original_text,
        span=span,
        replacement_content="",
    )
    diff_text = _build_replace_block_diff(
        target_path=target_path,
        original_text=original_text,
        new_text=updated_text,
    )
    ok, validate_error = _validate_delete_block_diff(
        diff_text=diff_text,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok or not diff_text:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=validate_error or OPERATION_VALIDATION_FAILED,
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
