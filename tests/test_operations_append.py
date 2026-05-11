from __future__ import annotations

from pathlib import Path

from aegis_code.operations import append as append_ops


def test_operations_append_parse_invalid_json_is_stable_error() -> None:
    ok, content, err = append_ops._parse_append_provider_response("not-json")
    assert ok is False
    assert content is None
    assert err == "append_output_invalid"


def test_operations_append_python_syntax_invalid_is_stable_error() -> None:
    err = append_ops._append_python_sanity_error(
        target_path="tests/test_cli.py",
        original_text="def test_old():\n    assert True\n",
        appended_content="\ndef test_broken(:\n    assert True\n",
    )
    assert err == "append_syntax_invalid"


def test_operations_append_invalid_diff_validation_is_stable_error(tmp_path: Path) -> None:
    ok, err = append_ops._validate_append_diff(
        diff_text="diff --git a/tests/test_cli.py b/tests/test_cli.py\n@@ -1 +1 @@\n+x\n",
        original_text="def test_old():\n    assert True\n",
        target_path="tests/test_cli.py",
        cwd=tmp_path,
    )
    assert ok is False
    assert err == "invalid_append_operation"

