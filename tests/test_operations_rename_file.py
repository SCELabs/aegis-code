from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, normalize_operation_contract
from aegis_code.operations import rename_file as rename_file_ops


def _request(tmp_path: Path, *, source_path: str, destination_path: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="rename-file",
            target_file=source_path,
            destination_path=destination_path,
            allow_deletions=True,
            allow_new_file=True,
            source="cli",
        ),
        task="rename file",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini"},
        failures={},
        patch_plan={"allowed_targets": [source_path]},
        aegis_execution={},
        model="gpt-4.1-mini",
        destination_path=destination_path,
    )


def test_rename_file_operation_generates_valid_rename_diff(tmp_path: Path) -> None:
    source = tmp_path / "src" / "old_name.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    result = rename_file_ops.run_rename_file_operation(
        _request(tmp_path, source_path="src/old_name.py", destination_path="src/new_name.py")
    )
    assert result.status == "generated"
    assert result.error is None
    assert "similarity index 100%" in result.diff_text
    assert "rename from src/old_name.py" in result.diff_text
    assert "rename to src/new_name.py" in result.diff_text


def test_rename_file_operation_blocks_when_source_equals_destination(tmp_path: Path) -> None:
    source = tmp_path / "src" / "same.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x = 1\n", encoding="utf-8")
    result = rename_file_ops.run_rename_file_operation(
        _request(tmp_path, source_path="src/same.py", destination_path="src/same.py")
    )
    assert result.status == "blocked"
    assert result.error == "operation_contract_invalid"


def test_rename_file_operation_source_missing(tmp_path: Path) -> None:
    result = rename_file_ops.run_rename_file_operation(
        _request(tmp_path, source_path="src/missing.py", destination_path="src/new_name.py")
    )
    assert result.status == "unavailable"
    assert result.error == "operation_target_missing"


def test_rename_file_operation_destination_exists(tmp_path: Path) -> None:
    source = tmp_path / "src" / "old_name.py"
    destination = tmp_path / "src" / "new_name.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("x = 1\n", encoding="utf-8")
    destination.write_text("y = 2\n", encoding="utf-8")
    result = rename_file_ops.run_rename_file_operation(
        _request(tmp_path, source_path="src/old_name.py", destination_path="src/new_name.py")
    )
    assert result.status == "blocked"
    assert result.error == "operation_target_exists"


def test_rename_file_diff_preserves_content_exactly(tmp_path: Path) -> None:
    original_text = "line 1\nline 2\nline 3\n"
    diff_text = rename_file_ops._build_rename_file_diff(
        source_path="src/old_name.py",
        destination_path="src/new_name.py",
        original_text=original_text,
    )
    valid, err = rename_file_ops._validate_rename_file_diff(
        diff_text=diff_text,
        source_path="src/old_name.py",
        destination_path="src/new_name.py",
        cwd=tmp_path,
    )
    assert valid is True
    assert err is None
    assert " line 1" in diff_text and " line 2" in diff_text and " line 3" in diff_text
    assert "-line 1" not in diff_text
    assert "+line 1" not in diff_text
