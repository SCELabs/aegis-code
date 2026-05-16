from __future__ import annotations

from typing import TYPE_CHECKING

from aegis_code.operations.rename_file import run_rename_file_operation

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def run_move_file_operation(request: OperationRequest) -> OperationResult:
    # move-file is a semantic alias of deterministic rename-style relocation.
    return run_rename_file_operation(request)
