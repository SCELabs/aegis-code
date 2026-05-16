from __future__ import annotations

import json
from pathlib import Path

import pytest

from aegis_code.batch_schema import load_batch_definition, validate_batch_definition


def _write_batch(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / ".aegis" / "batch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_load_batch_definition_valid_batch_succeeds(tmp_path: Path) -> None:
    path = _write_batch(
        tmp_path,
        {
            "version": 1,
            "operations": [
                {"operation": "create-file", "target_file": "src/utils.js", "task": "Create utility helpers."},
                {"operation": "replace-symbol", "target_file": "src/main.js", "symbol": "run", "task": "Use helpers."},
            ],
            "options": {"stop_on_first_failure": True},
        },
    )
    definition = load_batch_definition(path)
    assert definition.version == 1
    assert len(definition.operations) == 2
    assert definition.operations[0].operation == "create-file"
    assert definition.operations[1].symbol == "run"
    assert definition.stop_on_first_failure is True


def test_validate_batch_definition_version_mismatch_fails() -> None:
    with pytest.raises(ValueError, match="version must be 1"):
        validate_batch_definition({"version": 2, "operations": [{"operation": "append", "target_file": "README.md", "task": "x"}]})


def test_validate_batch_definition_empty_operations_fails() -> None:
    with pytest.raises(ValueError, match="non-empty operations list"):
        validate_batch_definition({"version": 1, "operations": []})


def test_validate_batch_definition_unsupported_operation_fails() -> None:
    with pytest.raises(ValueError, match="unsupported operation"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "unknown-op", "target_file": "README.md", "task": "x"}]})


def test_validate_batch_definition_nested_batch_fails() -> None:
    with pytest.raises(ValueError, match="nested batch"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "batch", "target_file": "x", "task": "x"}]})


def test_validate_batch_definition_missing_required_fields_fail() -> None:
    with pytest.raises(ValueError, match="missing required field: operation"):
        validate_batch_definition({"version": 1, "operations": [{"target_file": "README.md", "task": "x"}]})
    with pytest.raises(ValueError, match="missing required field: target_file"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "append", "task": "x"}]})


def test_validate_batch_definition_step_specific_requirements_enforced() -> None:
    with pytest.raises(ValueError, match="requires symbol"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "replace-symbol", "target_file": "src/main.js", "task": "x"}]})
    with pytest.raises(ValueError, match="requires anchor"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "replace-block", "target_file": "src/main.js", "task": "x"}]})
    with pytest.raises(ValueError, match="requires destination_path"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "move-file", "target_file": "src/main.js", "task": "x"}]})


def test_validate_batch_definition_empty_task_fails() -> None:
    with pytest.raises(ValueError, match="non-empty task"):
        validate_batch_definition({"version": 1, "operations": [{"operation": "append", "target_file": "README.md", "task": "  "}]})


def test_load_batch_definition_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / ".aegis" / "batch.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ invalid json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_batch_definition(path)
