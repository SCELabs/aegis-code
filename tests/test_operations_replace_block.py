from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationDependencies, OperationRequest, normalize_operation_contract
from aegis_code.operations import replace_block as replace_block_ops


def test_resolve_replace_block_span_unique_match() -> None:
    ok, span, err = replace_block_ops.resolve_replace_block_span(
        original_text="line 1\nOLD BLOCK\nline 3\n",
        anchor="OLD BLOCK",
    )
    assert ok is True
    assert span == (7, 16)
    assert err is None


def test_resolve_replace_block_span_not_found() -> None:
    ok, span, err = replace_block_ops.resolve_replace_block_span(
        original_text="line 1\nOLD BLOCK\nline 3\n",
        anchor="MISSING",
    )
    assert ok is False
    assert span is None
    assert err == "operation_anchor_not_found"


def test_resolve_replace_block_span_ambiguous() -> None:
    ok, span, err = replace_block_ops.resolve_replace_block_span(
        original_text="same\nx\nsame\n",
        anchor="same",
    )
    assert ok is False
    assert span is None
    assert err == "operation_anchor_ambiguous"


def test_replace_block_span_replaces_only_matched_range() -> None:
    new_text = replace_block_ops.replace_block_span(
        original_text="line 1\nOLD BLOCK\nline 3\n",
        span=(7, 16),
        replacement_content="NEW BLOCK",
    )
    assert new_text == "line 1\nNEW BLOCK\nline 3\n"


def test_parse_replace_block_provider_response_rejects_unified_diff() -> None:
    ok, content, err = replace_block_ops._parse_replace_block_provider_response(
        "diff --git a/src/main.py b/src/main.py\n@@ -1 +1 @@\n-old\n+new\n"
    )
    assert ok is False
    assert content is None
    assert err == "replace_block_output_invalid"


def test_validate_replace_block_diff_allows_controlled_deletions(tmp_path: Path) -> None:
    original = "line 1\nOLD BLOCK\nline 3\n"
    replaced = "line 1\nline 3\n"
    diff = replace_block_ops._build_replace_block_diff(
        target_path="src/helpers.js",
        original_text=original,
        new_text=replaced,
    )
    valid, err = replace_block_ops._validate_replace_block_diff(
        diff_text=diff,
        target_path="src/helpers.js",
        cwd=tmp_path,
    )
    assert valid is True
    assert err is None


def test_replace_block_operation_generates_local_diff(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"NEW BLOCK"}',
            "error": None,
        },
        build_replace_block_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-block",
            target_file="src/helpers.js",
            anchor="OLD BLOCK",
            allow_deletions=True,
            source="cli",
        ),
        task="replace block",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = replace_block_ops.run_replace_block_operation(request)
    assert result.status == "generated"
    assert "-OLD BLOCK" in result.diff_text
    assert "+NEW BLOCK" in result.diff_text


def test_replace_block_operation_with_preresolved_span_does_not_research_anchor(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"OLD BLOCK\\nNEW BLOCK"}',
            "error": None,
        },
        build_replace_block_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-block",
            target_file="src/helpers.js",
            anchor="OLD BLOCK",
            allow_deletions=True,
            source="cli",
        ),
        task="replace block",
        cwd=tmp_path,
        context={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "failure_context": {"files": []},
            "replace_original_text": "line 1\nOLD BLOCK\nline 3\n",
            "replace_anchor_span": (7, 16),
        },
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = replace_block_ops.run_replace_block_operation(request)
    assert result.status == "generated"
    assert "operation_anchor_ambiguous" not in (result.error or "")
