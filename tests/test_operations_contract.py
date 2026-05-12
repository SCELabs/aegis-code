from __future__ import annotations

from aegis_code.operations.contract import OperationContract, normalize_operation_contract
from aegis_code.operations.errors import (
    APPEND_OUTPUT_INVALID,
    APPEND_SEMANTIC_SUSPICIOUS,
    APPEND_SOURCE_CONFLICT,
    APPEND_SYNTAX_INVALID,
    CREATE_FILE_OUTPUT_INVALID,
    INVALID_APPEND_OPERATION,
    NO_APPEND_NEEDED,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_BUDGET_EXCEEDED,
    OPERATION_CONTRACT_INVALID,
    OPERATION_POLICY_BLOCKED,
    OPERATION_SYMBOL_NOT_FOUND,
    OPERATION_TARGET_EXISTS,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
)


def test_operation_contract_defaults() -> None:
    contract = OperationContract(operation="append", target_file="tests/test_cli.py")
    assert contract.operation == "append"
    assert contract.target_file == "tests/test_cli.py"
    assert contract.anchor is None
    assert contract.symbol is None
    assert contract.allow_deletions is False
    assert contract.allow_new_file is False
    assert contract.max_changed_lines is None
    assert contract.source == "unknown"


def test_normalize_operation_contract_preserves_explicit_operation_and_target_file() -> None:
    contract = normalize_operation_contract(
        operation="append",
        target_file="src/notes.js",
        source="cli",
    )
    assert contract.operation == "append"
    assert contract.target_file == "src/notes.js"
    assert contract.source == "cli"


def test_operation_error_constants_match_stable_string_values() -> None:
    assert OPERATION_CONTRACT_INVALID == "operation_contract_invalid"
    assert OPERATION_TARGET_MISSING == "operation_target_missing"
    assert OPERATION_ANCHOR_NOT_FOUND == "operation_anchor_not_found"
    assert OPERATION_SYMBOL_NOT_FOUND == "operation_symbol_not_found"
    assert OPERATION_BUDGET_EXCEEDED == "operation_budget_exceeded"
    assert OPERATION_VALIDATION_FAILED == "operation_validation_failed"
    assert OPERATION_POLICY_BLOCKED == "operation_policy_blocked"
    assert OPERATION_TARGET_EXISTS == "operation_target_exists"
    assert CREATE_FILE_OUTPUT_INVALID == "create_file_output_invalid"
    assert APPEND_OUTPUT_INVALID == "append_output_invalid"
    assert APPEND_SYNTAX_INVALID == "append_syntax_invalid"
    assert APPEND_SEMANTIC_SUSPICIOUS == "append_semantic_suspicious"
    assert INVALID_APPEND_OPERATION == "invalid_append_operation"
    assert APPEND_SOURCE_CONFLICT == "append_source_conflict"
    assert NO_APPEND_NEEDED == "no_append_needed"
