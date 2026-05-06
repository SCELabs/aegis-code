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
