from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.operations import OperationRequest, OperationResult, run_operation
from aegis_code.operations.contract import OperationContract


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
    request = OperationRequest(
        contract=contract,
        task=task,
        cwd=cwd,
        context=context,
        failures=failures,
        patch_plan=patch_plan,
        aegis_execution=aegis_execution,
        model=model,
        provider_timeout=provider_timeout,
    )
    return run_operation(request)
