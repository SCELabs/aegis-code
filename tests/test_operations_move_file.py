from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, normalize_operation_contract
from aegis_code.operations import move_file as move_file_ops


def _request(tmp_path: Path, *, source_path: str, destination_path: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="move-file",
            target_file=source_path,
            destination_path=destination_path,
            allow_deletions=True,
            allow_new_file=True,
            source="cli",
        ),
        task="move file",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini"},
        failures={},
        patch_plan={"allowed_targets": [source_path]},
        aegis_execution={},
        model="gpt-4.1-mini",
        destination_path=destination_path,
    )


def test_move_file_operation_generates_valid_rename_style_diff(tmp_path: Path) -> None:
    source = tmp_path / "src" / "utils.js"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const value = 1;\n", encoding="utf-8")
    result = move_file_ops.run_move_file_operation(
        _request(tmp_path, source_path="src/utils.js", destination_path="src/lib/utils.js")
    )
    assert result.status == "generated"
    assert result.error is None
    assert "similarity index 100%" in result.diff_text
    assert "rename from src/utils.js" in result.diff_text
    assert "rename to src/lib/utils.js" in result.diff_text


def test_move_file_operation_blocks_when_source_equals_destination(tmp_path: Path) -> None:
    source = tmp_path / "src" / "same.js"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const x = 1;\n", encoding="utf-8")
    result = move_file_ops.run_move_file_operation(
        _request(tmp_path, source_path="src/same.js", destination_path="src/same.js")
    )
    assert result.status == "blocked"
    assert result.error == "operation_contract_invalid"


def test_move_file_operation_source_missing(tmp_path: Path) -> None:
    result = move_file_ops.run_move_file_operation(
        _request(tmp_path, source_path="src/missing.js", destination_path="src/lib/utils.js")
    )
    assert result.status == "unavailable"
    assert result.error == "operation_target_missing"


def test_move_file_operation_destination_exists(tmp_path: Path) -> None:
    source = tmp_path / "src" / "utils.js"
    destination = tmp_path / "src" / "lib" / "utils.js"
    source.parent.mkdir(parents=True, exist_ok=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("export const value = 1;\n", encoding="utf-8")
    destination.write_text("export const value = 2;\n", encoding="utf-8")
    result = move_file_ops.run_move_file_operation(
        _request(tmp_path, source_path="src/utils.js", destination_path="src/lib/utils.js")
    )
    assert result.status == "blocked"
    assert result.error == "operation_target_exists"


def test_move_file_diff_preserves_content_exactly(tmp_path: Path) -> None:
    source = tmp_path / "src" / "utils.js"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("line 1\nline 2\n", encoding="utf-8")
    result = move_file_ops.run_move_file_operation(
        _request(tmp_path, source_path="src/utils.js", destination_path="src/lib/utils.js")
    )
    assert result.status == "generated"
    assert " line 1" in result.diff_text
    assert " line 2" in result.diff_text
    assert "-line 1" not in result.diff_text
    assert "+line 1" not in result.diff_text
