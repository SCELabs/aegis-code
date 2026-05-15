from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationRequest, normalize_operation_contract
from aegis_code.operations import delete_symbol as delete_symbol_ops


def _request(tmp_path: Path, *, target_file: str, symbol: str) -> OperationRequest:
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="delete-symbol",
            target_file=target_file,
            symbol=symbol,
            allow_deletions=True,
            source="cli",
        ),
        task="delete obsolete symbol",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini"},
        failures={},
        patch_plan={"allowed_targets": [target_file]},
        aegis_execution={},
        model="gpt-4.1-mini",
    )


def test_delete_symbol_python_function(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def keep():\n    return 1\n\ndef remove_me():\n    return 2\n", encoding="utf-8")
    result = delete_symbol_ops.run_delete_symbol_operation(
        _request(tmp_path, target_file="src/notes.py", symbol="remove_me")
    )
    assert result.status == "generated"
    assert "-def remove_me():" in result.diff_text
    assert "+def keep():" not in result.diff_text


def test_delete_symbol_python_class(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("class Keep:\n    pass\n\nclass RemoveMe:\n    pass\n", encoding="utf-8")
    result = delete_symbol_ops.run_delete_symbol_operation(
        _request(tmp_path, target_file="src/notes.py", symbol="RemoveMe")
    )
    assert result.status == "generated"
    assert "-class RemoveMe:" in result.diff_text


def test_delete_symbol_js_function(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "export function keep() {\n  return 1;\n}\n\nexport function removeMe() {\n  return 2;\n}\n",
        encoding="utf-8",
    )
    result = delete_symbol_ops.run_delete_symbol_operation(
        _request(tmp_path, target_file="src/notes.js", symbol="removeMe")
    )
    assert result.status == "generated"
    assert "-export function removeMe() {" in result.diff_text


def test_delete_symbol_symbol_not_found(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function keep() {\n  return 1;\n}\n", encoding="utf-8")
    result = delete_symbol_ops.run_delete_symbol_operation(
        _request(tmp_path, target_file="src/notes.js", symbol="missing")
    )
    assert result.status == "blocked"
    assert result.error == "operation_symbol_not_found"


def test_delete_symbol_symbol_ambiguous(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "function dup() {\n  return 1;\n}\n\nfunction dup() {\n  return 2;\n}\n",
        encoding="utf-8",
    )
    result = delete_symbol_ops.run_delete_symbol_operation(
        _request(tmp_path, target_file="src/notes.js", symbol="dup")
    )
    assert result.status == "blocked"
    assert result.error == "operation_symbol_ambiguous"


def test_delete_symbol_span_removes_only_target_range() -> None:
    text = "a\nfunction x() {\n  return 1;\n}\nb\n"
    from aegis_code.operations.replace_symbol import resolve_symbol_span

    ok, span, _ = resolve_symbol_span(original_text=text, symbol="x", target_path="src/notes.js")
    assert ok is True and span is not None
    new_text = delete_symbol_ops.delete_symbol_span(
        original_text=text,
        span=span,
    )
    assert new_text == "a\n\nb\n"
