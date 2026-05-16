from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.operations import (
    OperationDependencies,
    OperationRequest,
    OperationResult,
    run_operation,
)
from aegis_code.operations.contract import OperationContract


def _build_operation_dependencies(context: dict[str, Any]) -> OperationDependencies:
    return OperationDependencies(
        run_with_provider_heartbeat=context.get("run_with_provider_heartbeat")
        if callable(context.get("run_with_provider_heartbeat"))
        else None,
        generate_text=context.get("generate_text") if callable(context.get("generate_text")) else None,
        generate_structured_edits=context.get("generate_structured_edits")
        if callable(context.get("generate_structured_edits"))
        else None,
        build_create_file_prompt=context.get("build_create_file_prompt")
        if callable(context.get("build_create_file_prompt"))
        else None,
        build_insert_after_prompt=context.get("build_insert_after_prompt")
        if callable(context.get("build_insert_after_prompt"))
        else None,
        build_insert_before_prompt=context.get("build_insert_before_prompt")
        if callable(context.get("build_insert_before_prompt"))
        else None,
        build_replace_block_prompt=context.get("build_replace_block_prompt")
        if callable(context.get("build_replace_block_prompt"))
        else None,
        build_replace_file_prompt=context.get("build_replace_file_prompt")
        if callable(context.get("build_replace_file_prompt"))
        else None,
        build_replace_symbol_prompt=context.get("build_replace_symbol_prompt")
        if callable(context.get("build_replace_symbol_prompt"))
        else None,
        task_options=context.get("task_options"),
        api_key_env=str(context.get("api_key_env")) if context.get("api_key_env") is not None else None,
        base_url=str(context.get("base_url")) if context.get("base_url") is not None else None,
        max_context_chars=int(context.get("max_context_chars"))
        if isinstance(context.get("max_context_chars"), int)
        else None,
        append_python_sanity_error=context.get("append_python_sanity_error")
        if callable(context.get("append_python_sanity_error"))
        else None,
        validate_append_diff=context.get("validate_append_diff")
        if callable(context.get("validate_append_diff"))
        else None,
    )


def run_operation_stage(
    *,
    contract: OperationContract,
    task: str,
    cwd: Path,
    context: dict[str, Any],
    failures: dict[str, Any],
    patch_plan: dict[str, Any],
    aegis_execution: dict[str, Any],
    model: str,
    provider_timeout: int | None = None,
) -> OperationResult:
    normalized_context = context if isinstance(context, dict) else {}
    request = OperationRequest(
        contract=contract,
        task=task,
        cwd=cwd,
        context=normalized_context,
        failures=failures,
        patch_plan=patch_plan,
        aegis_execution=aegis_execution,
        model=model,
        destination_path=contract.destination_path,
        dependencies=_build_operation_dependencies(normalized_context),
        provider_timeout=provider_timeout,
    )
    return run_operation(request)
