from __future__ import annotations

from aegis_code.operations.contract import OperationContract, normalize_operation_contract
from aegis_code.operations.create_file import (
    _build_create_file_diff,
    _parse_create_file_provider_response,
    _target_exists,
    _validate_create_file_diff,
)
from aegis_code.operations.errors import (
    APPEND_OUTPUT_INVALID,
    APPEND_SEMANTIC_SUSPICIOUS,
    APPEND_SOURCE_CONFLICT,
    APPEND_SYNTAX_INVALID,
    INVALID_APPEND_OPERATION,
    NO_APPEND_NEEDED,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_BUDGET_EXCEEDED,
    OPERATION_CONTRACT_INVALID,
    OPERATION_POLICY_BLOCKED,
    OPERATION_SYMBOL_NOT_FOUND,
    OPERATION_TARGET_MISSING,
    OPERATION_TARGET_EXISTS,
    OPERATION_VALIDATION_FAILED,
    CREATE_FILE_OUTPUT_INVALID,
)

__all__ = [
    "OperationContract",
    "normalize_operation_contract",
    "OPERATION_CONTRACT_INVALID",
    "OPERATION_TARGET_MISSING",
    "OPERATION_ANCHOR_NOT_FOUND",
    "OPERATION_SYMBOL_NOT_FOUND",
    "OPERATION_BUDGET_EXCEEDED",
    "OPERATION_VALIDATION_FAILED",
    "OPERATION_POLICY_BLOCKED",
    "OPERATION_TARGET_EXISTS",
    "CREATE_FILE_OUTPUT_INVALID",
    "APPEND_OUTPUT_INVALID",
    "APPEND_SYNTAX_INVALID",
    "APPEND_SEMANTIC_SUSPICIOUS",
    "INVALID_APPEND_OPERATION",
    "APPEND_SOURCE_CONFLICT",
    "NO_APPEND_NEEDED",
    "_parse_create_file_provider_response",
    "_build_create_file_diff",
    "_target_exists",
    "_validate_create_file_diff",
]
