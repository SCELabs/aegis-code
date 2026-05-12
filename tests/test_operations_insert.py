from __future__ import annotations

from pathlib import Path

from aegis_code.operations import insert as insert_ops


def test_insert_parse_invalid_json_returns_insert_output_invalid() -> None:
    ok, content, err = insert_ops._parse_insert_provider_response("not-json")
    assert ok is False
    assert content is None
    assert err == "insert_output_invalid"


def test_insert_anchor_not_found_returns_operation_anchor_not_found() -> None:
    ok, new_text, err = insert_ops._insert_after_anchor(
        original_text="line a\nline b\n",
        anchor="missing anchor",
        insert_content="inserted\n",
    )
    assert ok is False
    assert new_text is None
    assert err == "operation_anchor_not_found"


def test_insert_anchor_without_full_line_does_not_match_function_signature() -> None:
    ok, new_text, err = insert_ops._insert_after_anchor(
        original_text="export function completeNote(notes, index) {\n  return notes;\n}\n",
        anchor="export function completeNote",
        insert_content="inserted\n",
    )
    assert ok is False
    assert new_text is None
    assert err == "operation_anchor_not_found"


def test_insert_exact_full_line_anchor_matches_once_and_succeeds() -> None:
    ok, new_text, err = insert_ops._insert_after_anchor(
        original_text="export function completeNote(notes, index) {\n  return notes;\n}\n",
        anchor="export function completeNote(notes, index) {",
        insert_content="inserted\n",
    )
    assert ok is True
    assert isinstance(new_text, str)
    assert err is None
    assert "inserted\n  return notes;" in str(new_text)


def test_insert_anchor_duplicate_returns_operation_anchor_ambiguous() -> None:
    ok, new_text, err = insert_ops._insert_after_anchor(
        original_text="same\nx\nsame\n",
        anchor="same",
        insert_content="inserted\n",
    )
    assert ok is False
    assert new_text is None
    assert err == "operation_anchor_ambiguous"


def test_insert_success_builds_zero_deletion_diff(tmp_path: Path) -> None:
    original = "a\nanchor line\nb\n"
    ok, new_text, err = insert_ops._insert_after_anchor(
        original_text=original,
        anchor="anchor line",
        insert_content="inserted line\n",
    )
    assert ok is True
    assert err is None
    assert isinstance(new_text, str)
    diff = insert_ops._build_insert_after_diff(
        target_path="src/helpers.js",
        original_text=original,
        new_text=str(new_text),
    )
    valid, validate_err = insert_ops._validate_insert_diff(
        diff_text=diff,
        target_path="src/helpers.js",
        cwd=tmp_path,
    )
    assert valid is True
    assert validate_err is None
