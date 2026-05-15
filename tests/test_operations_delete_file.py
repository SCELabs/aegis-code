from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, normalize_operation_contract
from aegis_code.operations import delete_file as delete_file_ops


def _request(tmp_path: Path, *, target_file: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="delete-file",
            target_file=target_file,
            allow_deletions=True,
            source="cli",
        ),
        task="delete obsolete file",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini"},
        failures={},
        patch_plan={"allowed_targets": [target_file]},
        aegis_execution={},
        model="gpt-4.1-mini",
    )


def test_delete_file_operation_generates_deletion_diff(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "old-notes.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Old notes\n\nDeprecated.\n", encoding="utf-8")
    result = delete_file_ops.run_delete_file_operation(
        _request(tmp_path, target_file="docs/old-notes.md")
    )
    assert result.status == "generated"
    assert result.error is None
    assert "--- a/docs/old-notes.md" in result.diff_text
    assert "+++ /dev/null" in result.diff_text
    assert "+# Old notes" not in result.diff_text


def test_delete_file_operation_target_missing(tmp_path: Path) -> None:
    result = delete_file_ops.run_delete_file_operation(
        _request(tmp_path, target_file="docs/missing.md")
    )
    assert result.status == "unavailable"
    assert result.error == "operation_target_missing"


def test_validate_delete_file_diff_requires_deleted_file_semantics(tmp_path: Path) -> None:
    invalid_diff = (
        "diff --git a/docs/old-notes.md b/docs/old-notes.md\n"
        "--- a/docs/old-notes.md\n"
        "+++ b/docs/old-notes.md\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    valid, err = delete_file_ops._validate_delete_file_diff(
        diff_text=invalid_diff,
        target_path="docs/old-notes.md",
        cwd=tmp_path,
    )
    assert valid is False
    assert err == "operation_validation_failed"
