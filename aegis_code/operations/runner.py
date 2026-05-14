from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from aegis_code.operations.contract import OperationContract


@dataclass(slots=True)
class OperationDependencies:
    run_with_provider_heartbeat: Callable[..., Any] | None = None
    generate_text: Callable[..., Any] | None = None
    generate_structured_edits: Callable[..., Any] | None = None
    build_create_file_prompt: Callable[..., str] | None = None
    build_insert_after_prompt: Callable[..., str] | None = None
    build_insert_before_prompt: Callable[..., str] | None = None
    build_replace_block_prompt: Callable[..., str] | None = None
    task_options: Any = None
    api_key_env: str | None = None
    base_url: str | None = None
    max_context_chars: int | None = None
    append_python_sanity_error: Callable[..., str | None] | None = None
    validate_append_diff: Callable[..., tuple[bool, str | None]] | None = None


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
    dependencies: OperationDependencies | None = None
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
    if operation == "insert-before":
        from aegis_code.operations.insert import run_insert_before_operation

        return run_insert_before_operation(request)
    if operation == "replace-block":
        from aegis_code.operations.replace_block import run_replace_block_operation

        return run_replace_block_operation(request)
    return OperationResult(
        attempted=False,
        status="blocked",
        error="operation_contract_invalid",
        operation=request.contract.operation,
        source=request.contract.source,
    )
