from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationDependencies, OperationRequest, normalize_operation_contract
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


def test_resolve_insert_after_index_and_insert_after_index_helpers() -> None:
    original = "a\nanchor line\nb\n"
    ok, index, err = insert_ops.resolve_insert_after_index(original_text=original, anchor="anchor line")
    assert ok is True
    assert index == 1
    assert err is None
    new_text = insert_ops.insert_after_index(original_text=original, index=int(index), insert_content="inserted\n")
    assert new_text == "a\nanchor line\ninserted\nb\n"


def test_insert_before_index_helper() -> None:
    original = "a\nanchor line\nb\n"
    new_text = insert_ops.insert_before_index(original_text=original, index=1, insert_content="inserted\n")
    assert new_text == "a\ninserted\nanchor line\nb\n"


def test_insert_before_operation_anchor_not_found_returns_operation_anchor_not_found(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("const a = 1;\n", encoding="utf-8")

    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        },
        build_insert_before_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-before",
            target_file="src/helpers.js",
            anchor="MISSING",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = insert_ops.run_insert_before_operation(request)
    assert result.status == "blocked"
    assert result.error == "operation_anchor_not_found"


def test_insert_before_operation_anchor_ambiguous_returns_operation_anchor_ambiguous(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("same\nx\nsame\n", encoding="utf-8")

    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        },
        build_insert_before_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-before",
            target_file="src/helpers.js",
            anchor="same",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = insert_ops.run_insert_before_operation(request)
    assert result.status == "blocked"
    assert result.error == "operation_anchor_ambiguous"


def test_insert_before_operation_generates_diff_inserting_before_anchor(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nTARGET\nline 3\n", encoding="utf-8")

    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"NEW LINE\\n"}',
            "error": None,
        },
        build_insert_before_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-before",
            target_file="src/helpers.js",
            anchor="TARGET",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = insert_ops.run_insert_before_operation(request)
    assert result.status == "generated"
    assert "+NEW LINE" in result.diff_text
    assert "line 1\n+NEW LINE\n TARGET" in result.diff_text


def test_insert_after_operation_blocks_when_provider_content_repeats_anchor(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nTARGET\nline 3\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"TARGET\\nNEW LINE\\n"}',
            "error": None,
        },
        build_insert_after_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-after",
            target_file="src/helpers.js",
            anchor="TARGET",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = insert_ops.run_insert_after_operation(request)
    assert result.status == "blocked"
    assert result.error == "insert_output_invalid"


def test_insert_before_operation_blocks_when_provider_content_repeats_anchor(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nTARGET\nline 3\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"TARGET\\nNEW LINE\\n"}',
            "error": None,
        },
        build_insert_before_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-before",
            target_file="src/helpers.js",
            anchor="TARGET",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = insert_ops.run_insert_before_operation(request)
    assert result.status == "blocked"
    assert result.error == "insert_output_invalid"
