from __future__ import annotations

from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING

from aegis_code.operations.errors import (
    OPERATION_CONTRACT_INVALID,
    OPERATION_SYMBOL_AMBIGUOUS,
    OPERATION_SYMBOL_NOT_FOUND,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
)
from aegis_code.operations.replace_symbol import resolve_symbol_span
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def delete_symbol_span(
    *,
    original_text: str,
    span: tuple[int, int],
) -> str:
    start, end = int(span[0]), int(span[1])
    return str(original_text or "")[:start] + str(original_text or "")[end:]


def _build_delete_symbol_diff(*, target_path: str, original_text: str, new_text: str) -> str:
    old_lines = str(original_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _validate_delete_symbol_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
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


def run_delete_symbol_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    target_path = str(request.contract.target_file or "").strip()
    symbol = str(request.contract.symbol or "").strip()
    if not target_path or not symbol:
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

    original_text = target_file.read_text(encoding="utf-8", errors="replace")
    span_ok, span, span_error = resolve_symbol_span(
        original_text=original_text,
        symbol=symbol,
        target_path=target_path,
    )
    if not span_ok or span is None:
        resolved_error = span_error or OPERATION_SYMBOL_NOT_FOUND
        if resolved_error not in {OPERATION_SYMBOL_NOT_FOUND, OPERATION_SYMBOL_AMBIGUOUS}:
            resolved_error = OPERATION_SYMBOL_NOT_FOUND
        return OperationResult(
            attempted=True,
            status="blocked",
            error=resolved_error,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    new_text = delete_symbol_span(
        original_text=original_text,
        span=span,
    )
    diff_text = _build_delete_symbol_diff(
        target_path=target_path,
        original_text=original_text,
        new_text=new_text,
    )
    ok, validate_error = _validate_delete_symbol_diff(
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
