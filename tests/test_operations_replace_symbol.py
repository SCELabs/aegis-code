from __future__ import annotations

import json
from pathlib import Path

from aegis_code.operations import OperationDependencies, OperationRequest, normalize_operation_contract
from aegis_code.operations import replace_symbol as replace_symbol_ops


def test_resolve_symbol_span_python_function() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="def add_note(text):\n    return text\n",
        symbol="add_note",
        target_path="src/notes.py",
    )
    assert ok is True
    assert span is not None
    assert err is None


def test_resolve_symbol_span_python_class() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="class NotesService:\n    pass\n",
        symbol="NotesService",
        target_path="src/notes.py",
    )
    assert ok is True
    assert span is not None
    assert err is None


def test_resolve_symbol_span_js_exported_function() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="export function addNote(text) {\n  return text;\n}\n",
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is True
    assert span is not None
    assert err is None


def test_resolve_symbol_span_js_plain_function() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="function addNote(text) {\n  return text;\n}\n",
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is True
    assert span is not None
    assert err is None


def test_resolve_symbol_span_js_exported_const_arrow() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="export const addNote = (text) => {\n  return text;\n};\n",
        symbol="addNote",
        target_path="src/notes.ts",
    )
    assert ok is True
    assert span is not None
    assert err is None


def test_resolve_symbol_span_not_found() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="function addNote(text) {\n  return text;\n}\n",
        symbol="missing",
        target_path="src/notes.js",
    )
    assert ok is False
    assert span is None
    assert err == "operation_symbol_not_found"


def test_resolve_symbol_span_ambiguous() -> None:
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text="function addNote(text) {\n  return text;\n}\nfunction addNote(text) {\n  return text;\n}\n",
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is False
    assert span is None
    assert err == "operation_symbol_ambiguous"


def test_replace_symbol_span_replaces_only_resolved_range() -> None:
    original = "const start = 1;\nfunction addNote(text) {\n  return text;\n}\nconst end = 2;\n"
    ok, span, _ = replace_symbol_ops.resolve_symbol_span(
        original_text=original,
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is True and span is not None
    new_text = replace_symbol_ops.replace_symbol_span(
        original_text=original,
        span=span,
        replacement_content="function addNote(text) {\n  return text.trim();\n}\n",
    )
    assert "const start = 1;" in new_text
    assert "const end = 2;" in new_text
    assert "return text.trim();" in new_text


def test_parse_replace_symbol_provider_response_rejects_unified_diff() -> None:
    ok, content, err = replace_symbol_ops._parse_replace_symbol_provider_response(
        "diff --git a/src/notes.js b/src/notes.js\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert ok is False
    assert content is None
    assert err == "replace_symbol_output_invalid"


def test_parse_replace_symbol_provider_response_rejects_markdown() -> None:
    ok, content, err = replace_symbol_ops._parse_replace_symbol_provider_response(
        "```json\n{\"content\":\"function addNote() {}\"}\n```"
    )
    assert ok is False
    assert content is None
    assert err == "replace_symbol_output_invalid"


def test_parse_replace_symbol_provider_response_rejects_invalid_json() -> None:
    ok, content, err = replace_symbol_ops._parse_replace_symbol_provider_response("{not-json")
    assert ok is False
    assert content is None
    assert err == "replace_symbol_output_invalid"


def test_parse_replace_symbol_provider_response_rejects_empty_content() -> None:
    ok, content, err = replace_symbol_ops._parse_replace_symbol_provider_response('{"content":"   "}')
    assert ok is False
    assert content is None
    assert err == "replace_symbol_output_invalid"


def test_parse_replace_symbol_provider_response_rejects_markdown_fence_in_content() -> None:
    ok, content, err = replace_symbol_ops._parse_replace_symbol_provider_response(
        '{"content":"```js\\nfunction addNote() {}\\n```"}'
    )
    assert ok is False
    assert content is None
    assert err == "replace_symbol_output_invalid"


def test_replace_symbol_diff_validation_python_function_happy_path(tmp_path: Path) -> None:
    original = "def add_note(text):\n    return text\n\n\ndef keep_note(text):\n    return text\n"
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text=original,
        symbol="add_note",
        target_path="src/notes.py",
    )
    assert ok is True
    assert span is not None
    assert err is None
    replaced = replace_symbol_ops.replace_symbol_span(
        original_text=original,
        span=span,
        replacement_content=(
            "def add_note(text):\n"
            "    value = text.strip()\n"
            "    if not value:\n"
            "        raise ValueError('note text is required')\n"
            "    return value\n"
        ),
    )
    diff_text = replace_symbol_ops._build_replace_symbol_diff(
        target_path="src/notes.py",
        original_text=original,
        new_text=replaced,
    )
    valid, validate_err = replace_symbol_ops._validate_replace_symbol_diff(
        diff_text=diff_text,
        target_path="src/notes.py",
        cwd=tmp_path,
    )
    assert valid is True
    assert validate_err is None


def test_replace_symbol_diff_validation_js_function_happy_path(tmp_path: Path) -> None:
    original = (
        "export function addNote(text) {\n"
        "  return text;\n"
        "}\n\n"
        "export function keepNote(text) {\n"
        "  return text;\n"
        "}\n"
    )
    ok, span, err = replace_symbol_ops.resolve_symbol_span(
        original_text=original,
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is True
    assert span is not None
    assert err is None
    replaced = replace_symbol_ops.replace_symbol_span(
        original_text=original,
        span=span,
        replacement_content=(
            "export function addNote(text) {\n"
            "  const value = text.trim();\n"
            "  if (!value) {\n"
            "    throw new Error('note text required');\n"
            "  }\n"
            "  return value;\n"
            "}\n"
        ),
    )
    diff_text = replace_symbol_ops._build_replace_symbol_diff(
        target_path="src/notes.js",
        original_text=original,
        new_text=replaced,
    )
    valid, validate_err = replace_symbol_ops._validate_replace_symbol_diff(
        diff_text=diff_text,
        target_path="src/notes.js",
        cwd=tmp_path,
    )
    assert valid is True
    assert validate_err is None


def test_replace_symbol_operation_generates_local_diff(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function addNote(text) {\n  return text;\n}\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export function addNote(text) {\\n  const value = text.trim();\\n  if (!value) return null;\\n  return value;\\n}\\n"}',
            "error": None,
        },
        build_replace_symbol_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-symbol",
            target_file="src/notes.js",
            symbol="addNote",
            allow_deletions=True,
            source="cli",
        ),
        task="rewrite addNote",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/notes.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = replace_symbol_ops.run_replace_symbol_operation(request)
    assert result.status == "generated"
    assert "return text;" in result.diff_text
    assert "const value = text.trim();" in result.diff_text


def test_replace_symbol_operation_identical_content_returns_no_symbol_change(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    original_text = "export function addNote(text) {\n  return text;\n}\n"
    target.write_text(original_text, encoding="utf-8")
    ok, span, _ = replace_symbol_ops.resolve_symbol_span(
        original_text=original_text,
        symbol="addNote",
        target_path="src/notes.js",
    )
    assert ok is True
    assert span is not None
    identical_symbol_content = original_text[span[0] : span[1]]
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": json.dumps({"content": identical_symbol_content}),
            "error": None,
        },
        build_replace_symbol_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-symbol",
            target_file="src/notes.js",
            symbol="addNote",
            allow_deletions=True,
            source="cli",
        ),
        task="rewrite addNote",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/notes.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = replace_symbol_ops.run_replace_symbol_operation(request)
    assert result.status == "blocked"
    assert result.error == "no_symbol_change"
    assert result.diff_text == ""


def test_replace_symbol_operation_no_provider_call_when_symbol_missing(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function addNote(text) {\n  return text;\n}\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider should not run")),
        generate_text=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("provider should not run")),
        build_replace_symbol_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-symbol",
            target_file="src/notes.js",
            symbol="missingSymbol",
            allow_deletions=True,
            source="cli",
        ),
        task="rewrite symbol",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/notes.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = replace_symbol_ops.run_replace_symbol_operation(request)
    assert result.status == "blocked"
    assert result.error == "operation_symbol_not_found"
