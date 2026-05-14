from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aegis_code.operations.contract import OperationContract


@dataclass(slots=True)
class OperationRequest:
    contract: OperationContract
    task: str
    cwd: Path
    context: dict[str, Any]
    failures: dict[str, Any]
    patch_plan: dict[str, Any]
    aegis_execution: dict[str, Any]
    model: str
    provider_timeout: int | None = None


@dataclass(slots=True)
class OperationResult:
    attempted: bool
    status: str
    diff_text: str = ""
    error: str | None = None
    provider: str | None = None
    model: str | None = None
    validation_result: dict[str, Any] | None = None
    operation: str | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None


def run_operation(request: OperationRequest) -> OperationResult:
    """
    Dispatch to the appropriate operation implementation based on
    request.contract.operation.
    """
    operation = str(request.contract.operation or "").strip().lower()
    if operation == "append":
        from aegis_code.operations.append import run_append_operation

        return run_append_operation(request)
    if operation == "create-file":
        from aegis_code.operations.create_file import run_create_file_operation

        return run_create_file_operation(request)
    if operation == "insert-after":
        from aegis_code.operations.insert import run_insert_after_operation

        return run_insert_after_operation(request)
    return OperationResult(
        attempted=False,
        status="blocked",
        error="operation_contract_invalid",
        operation=request.contract.operation,
        source=request.contract.source,
    )
