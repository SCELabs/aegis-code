from __future__ import annotations

from pathlib import Path

from aegis_code.scope.contract import build_scope_contract_from_cli


def test_scope_contract_single_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "src" / "main.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x = 1\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(["src/main.py"], allow_create=False, max_files=None, cwd=tmp_path)
    assert contract.allowed_targets == ["src/main.py"]
    assert contract.block_reason is None
    assert contract.allowed_operations == ["replace"]


def test_scope_contract_multiple_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_cli.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/main.py", "tests/test_cli.py"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
    )
    assert sorted(contract.allowed_targets) == ["src/main.py", "tests/test_cli.py"]
    assert contract.max_files == 2


def test_scope_contract_missing_without_allow_create_blocks(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(["src/missing.py"], allow_create=False, max_files=None, cwd=tmp_path)
    assert contract.block_reason == "requested_target_missing"
    assert contract.missing_targets == ["src/missing.py"]


def test_scope_contract_missing_with_allow_create_is_allowed(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(["src/new_file.py"], allow_create=True, max_files=None, cwd=tmp_path)
    assert contract.block_reason is None
    assert contract.allowed_operations == ["create", "replace"]


def test_scope_contract_append_operation_requires_append_only(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["tests/test_cli.py"],
        allow_create=True,
        max_files=None,
        cwd=tmp_path,
        operation="append",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["append"]


def test_scope_contract_create_file_operation_requires_create_file_mode(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=True,
        max_files=None,
        cwd=tmp_path,
        operation="create-file",
    )
    assert contract.allow_new_files is True
    assert contract.allowed_operations == ["create-file"]
    assert contract.block_reason is None


def test_scope_contract_create_file_operation_allows_new_file_without_allow_create_flag(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="create-file",
    )
    assert contract.allow_new_files is True
    assert contract.allowed_operations == ["create-file"]
    assert contract.block_reason is None


def test_scope_contract_insert_after_operation_requires_insert_after_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="insert-after",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["insert-after"]
    assert contract.block_reason is None


def test_scope_contract_insert_before_operation_requires_insert_before_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="insert-before",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["insert-before"]
    assert contract.block_reason is None


def test_scope_contract_replace_block_operation_requires_replace_block_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="replace-block",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["replace-block"]
    assert contract.block_reason is None


def test_scope_contract_delete_block_operation_requires_delete_block_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="delete-block",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["delete-block"]
    assert contract.block_reason is None


def test_scope_contract_replace_file_operation_requires_replace_file_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="replace-file",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["replace-file"]
    assert contract.block_reason is None


def test_scope_contract_delete_file_operation_requires_delete_file_mode(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "old-notes.md").write_text("deprecated\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["docs/old-notes.md"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="delete-file",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["delete-file"]
    assert contract.block_reason is None


def test_scope_contract_replace_symbol_operation_requires_symbol_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("export function addNote(text) { return text; }\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="replace-symbol",
        symbol="addNote",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["replace-symbol"]
    assert contract.symbol == "addNote"
    assert contract.block_reason is None


def test_scope_contract_delete_symbol_operation_requires_symbol_mode(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("export function removeMe() { return 1; }\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/helpers.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="delete-symbol",
        symbol="removeMe",
    )
    assert contract.allow_new_files is False
    assert contract.allowed_operations == ["delete-symbol"]
    assert contract.symbol == "removeMe"
    assert contract.block_reason is None


def test_scope_contract_rename_file_operation_preserves_destination(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "old_name.py").write_text("x = 1\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/old_name.py"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="rename-file",
        destination_path="src/new_name.py",
    )
    assert contract.allow_new_files is True
    assert contract.allowed_operations == ["rename-file"]
    assert contract.destination_path == "src/new_name.py"
    assert contract.block_reason is None


def test_scope_contract_rename_file_blocks_when_source_missing(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(
        ["src/missing.py"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="rename-file",
        destination_path="src/new_name.py",
    )
    assert contract.block_reason == "requested_target_missing"
    assert contract.missing_targets == ["src/missing.py"]


def test_scope_contract_move_file_operation_preserves_destination(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "utils.js").write_text("export const x = 1;\n", encoding="utf-8")
    contract = build_scope_contract_from_cli(
        ["src/utils.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="move-file",
        destination_path="src/lib/utils.js",
    )
    assert contract.allow_new_files is True
    assert contract.allowed_operations == ["move-file"]
    assert contract.destination_path == "src/lib/utils.js"
    assert contract.block_reason is None


def test_scope_contract_move_file_blocks_when_source_missing(tmp_path: Path) -> None:
    contract = build_scope_contract_from_cli(
        ["src/missing.js"],
        allow_create=False,
        max_files=None,
        cwd=tmp_path,
        operation="move-file",
        destination_path="src/lib/utils.js",
    )
    assert contract.block_reason == "requested_target_missing"
    assert contract.missing_targets == ["src/missing.js"]
