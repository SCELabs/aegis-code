from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, normalize_operation_contract
from aegis_code.operations import delete_block as delete_block_ops


def _request(tmp_path: Path, *, target_file: str, anchor: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="delete-block",
            target_file=target_file,
            anchor=anchor,
            allow_deletions=True,
            source="cli",
        ),
        task="delete block",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini"},
        failures={},
        patch_plan={"allowed_targets": [target_file]},
        aegis_execution={},
        model="gpt-4.1-mini",
    )


def test_delete_block_operation_deletes_unique_anchor_block(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    result = delete_block_ops.run_delete_block_operation(
        _request(tmp_path, target_file="src/helpers.js", anchor="OLD BLOCK")
    )
    assert result.status == "generated"
    assert result.error is None
    assert "-OLD BLOCK" in result.diff_text
    assert "-line 1" not in result.diff_text
    assert "-line 3" not in result.diff_text


def test_delete_block_operation_anchor_not_found(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    result = delete_block_ops.run_delete_block_operation(
        _request(tmp_path, target_file="src/helpers.js", anchor="MISSING")
    )
    assert result.status == "blocked"
    assert result.error == "operation_anchor_not_found"


def test_delete_block_operation_anchor_ambiguous(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("SAME\nx\nSAME\n", encoding="utf-8")
    result = delete_block_ops.run_delete_block_operation(
        _request(tmp_path, target_file="src/helpers.js", anchor="SAME")
    )
    assert result.status == "blocked"
    assert result.error == "operation_anchor_ambiguous"


def test_delete_block_operation_does_not_call_provider(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    request = _request(tmp_path, target_file="src/helpers.js", anchor="OLD BLOCK")
    request.context["generate_text"] = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("provider should not be called for delete-block")
    )
    result = delete_block_ops.run_delete_block_operation(request)
    assert result.status == "generated"
