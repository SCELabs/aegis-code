from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, OperationResult, normalize_operation_contract, run_operation


def _request(operation: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation=operation,
            target_file="src/helpers.py",
            source="cli",
        ),
        task="task",
        cwd=Path.cwd(),
        context={},
        failures={},
        patch_plan={},
        aegis_execution={},
        model="gpt-4.1-mini",
    )


def test_run_operation_dispatches_append(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.append.run_append_operation", _fake)
    result = run_operation(_request("append"))
    assert seen == ["append"]
    assert result.status == "generated"


def test_run_operation_dispatches_create_file(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.create_file.run_create_file_operation", _fake)
    result = run_operation(_request("create-file"))
    assert seen == ["create-file"]
    assert result.status == "generated"


def test_run_operation_dispatches_insert_after(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.insert.run_insert_after_operation", _fake)
    result = run_operation(_request("insert-after"))
    assert seen == ["insert-after"]
    assert result.status == "generated"


def test_run_operation_dispatches_insert_before(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.insert.run_insert_before_operation", _fake)
    result = run_operation(_request("insert-before"))
    assert seen == ["insert-before"]
    assert result.status == "generated"


def test_run_operation_dispatches_replace_block(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.replace_block.run_replace_block_operation", _fake)
    result = run_operation(_request("replace-block"))
    assert seen == ["replace-block"]
    assert result.status == "generated"


def test_run_operation_dispatches_delete_block(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.delete_block.run_delete_block_operation", _fake)
    result = run_operation(_request("delete-block"))
    assert seen == ["delete-block"]
    assert result.status == "generated"


def test_run_operation_dispatches_replace_file(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.replace_file.run_replace_file_operation", _fake)
    result = run_operation(_request("replace-file"))
    assert seen == ["replace-file"]
    assert result.status == "generated"


def test_run_operation_dispatches_delete_file(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.delete_file.run_delete_file_operation", _fake)
    result = run_operation(_request("delete-file"))
    assert seen == ["delete-file"]
    assert result.status == "generated"


def test_run_operation_dispatches_replace_symbol(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.replace_symbol.run_replace_symbol_operation", _fake)
    result = run_operation(_request("replace-symbol"))
    assert seen == ["replace-symbol"]
    assert result.status == "generated"


def test_run_operation_dispatches_delete_symbol(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.delete_symbol.run_delete_symbol_operation", _fake)
    result = run_operation(_request("delete-symbol"))
    assert seen == ["delete-symbol"]
    assert result.status == "generated"


def test_run_operation_dispatches_rename_file(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.rename_file.run_rename_file_operation", _fake)
    result = run_operation(_request("rename-file"))
    assert seen == ["rename-file"]
    assert result.status == "generated"


def test_run_operation_dispatches_move_file(monkeypatch) -> None:
    seen: list[str] = []

    def _fake(request: OperationRequest) -> OperationResult:
        seen.append(request.contract.operation)
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.operations.move_file.run_move_file_operation", _fake)
    result = run_operation(_request("move-file"))
    assert seen == ["move-file"]
    assert result.status == "generated"


def test_run_operation_unsupported_operation_is_blocked() -> None:
    result = run_operation(_request("replace"))
    assert result.attempted is False
    assert result.status == "blocked"
    assert result.error == "operation_contract_invalid"
    assert result.operation == "replace"
    assert result.source == "cli"
