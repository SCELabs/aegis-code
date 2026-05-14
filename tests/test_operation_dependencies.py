from __future__ import annotations

from pathlib import Path

from aegis_code.operations import (
    OperationDependencies,
    OperationRequest,
    OperationResult,
    normalize_operation_contract,
)
from aegis_code.operations.append import run_append_operation
from aegis_code.operations.create_file import run_create_file_operation
from aegis_code.operations.insert import run_insert_after_operation
from aegis_code.operations.replace_block import run_replace_block_operation
from aegis_code.runtime_components.operation_stage import run_operation_stage


def test_operation_dependencies_constructible() -> None:
    deps = OperationDependencies(
        task_options={"x": 1},
        api_key_env="OPENAI_API_KEY",
        base_url="https://example.com",
        max_context_chars=4000,
    )
    assert deps.task_options == {"x": 1}
    assert deps.api_key_env == "OPENAI_API_KEY"
    assert deps.base_url == "https://example.com"
    assert deps.max_context_chars == 4000


def test_operation_stage_builds_and_passes_dependencies(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run_operation(request: OperationRequest) -> OperationResult:
        captured["request"] = request
        return OperationResult(attempted=True, status="generated", diff_text="diff")

    monkeypatch.setattr("aegis_code.runtime_components.operation_stage.run_operation", _fake_run_operation)
    contract = normalize_operation_contract(operation="append", target_file="tests/test_cli.py", source="cli")
    payload_context = {
        "run_with_provider_heartbeat": lambda *args, **kwargs: ({}, False),
        "generate_text": lambda **kwargs: {},
        "generate_structured_edits": lambda **kwargs: {},
        "build_create_file_prompt": lambda **kwargs: "prompt",
        "build_insert_after_prompt": lambda **kwargs: "prompt",
        "build_insert_before_prompt": lambda **kwargs: "prompt",
        "build_replace_block_prompt": lambda **kwargs: "prompt",
        "task_options": {"opt": True},
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "https://example.com",
        "max_context_chars": 1234,
        "append_python_sanity_error": lambda **kwargs: None,
        "validate_append_diff": lambda **kwargs: (True, None),
    }
    result = run_operation_stage(
        contract=contract,
        task="append tests",
        cwd=tmp_path,
        context=payload_context,
        failures={},
        patch_plan={},
        aegis_execution={},
        model="gpt-4.1-mini",
        provider_timeout=45,
    )
    assert result.status == "generated"
    request = captured.get("request")
    assert isinstance(request, OperationRequest)
    assert request.context == payload_context
    assert request.dependencies is not None
    deps = request.dependencies
    assert deps.task_options == {"opt": True}
    assert deps.api_key_env == "OPENAI_API_KEY"
    assert deps.base_url == "https://example.com"
    assert deps.max_context_chars == 1234
    assert callable(deps.run_with_provider_heartbeat)
    assert callable(deps.generate_text)
    assert callable(deps.generate_structured_edits)
    assert callable(deps.build_create_file_prompt)
    assert callable(deps.build_insert_after_prompt)
    assert callable(deps.build_insert_before_prompt)
    assert callable(deps.build_replace_block_prompt)
    assert callable(deps.append_python_sanity_error)
    assert callable(deps.validate_append_diff)


def test_append_operation_prefers_dependencies_over_context(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_old():\n    assert True\n", encoding="utf-8")

    def _good_heartbeat(_options, _label, fn, timeout_seconds=60):
        _ = timeout_seconds
        return fn(), False

    def _good_generate_structured_edits(**_kwargs):
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"\\n\\ndef test_new():\\n    assert 1 == 1\\n"}',
            "error": None,
        }

    deps = OperationDependencies(
        run_with_provider_heartbeat=_good_heartbeat,
        generate_structured_edits=_good_generate_structured_edits,
        task_options={"k": "v"},
        api_key_env="OPENAI_API_KEY",
        base_url="https://example.com",
        max_context_chars=8000,
        append_python_sanity_error=lambda **kwargs: None,
        validate_append_diff=lambda **kwargs: (True, None),
    )
    request = OperationRequest(
        contract=normalize_operation_contract(operation="append", target_file="tests/test_cli.py", source="cli"),
        task="append tests",
        cwd=tmp_path,
        context={
            "failure_context": {"files": []},
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "run_with_provider_heartbeat": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("context heartbeat should not run")),
            "generate_structured_edits": lambda **kwargs: (_ for _ in ()).throw(AssertionError("context structured edits should not run")),
            "append_python_sanity_error": lambda **kwargs: (_ for _ in ()).throw(AssertionError("context sanity should not run")),
            "validate_append_diff": lambda **kwargs: (_ for _ in ()).throw(AssertionError("context validate should not run")),
            "relevant_file_snippets": [],
        },
        failures={},
        patch_plan={"allowed_targets": ["tests/test_cli.py"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = run_append_operation(request)
    assert result.status == "generated"
    assert bool(result.diff_text)


def test_create_file_operation_falls_back_to_context_when_dependencies_missing(tmp_path: Path) -> None:
    called: dict[str, int] = {"heartbeat": 0, "text": 0, "prompt": 0}

    def _context_heartbeat(_options, _label, fn, timeout_seconds=60):
        _ = timeout_seconds
        called["heartbeat"] += 1
        return fn(), False

    def _context_generate_text(**_kwargs):
        called["text"] += 1
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export const x = 1;\\n"}',
            "error": None,
        }

    def _context_prompt_builder(**_kwargs):
        called["prompt"] += 1
        return "prompt"

    request = OperationRequest(
        contract=normalize_operation_contract(operation="create-file", target_file="src/helpers.js", source="cli"),
        task="create helper",
        cwd=tmp_path,
        context={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "failure_context": {"files": []},
            "run_with_provider_heartbeat": _context_heartbeat,
            "generate_text": _context_generate_text,
            "build_create_file_prompt": _context_prompt_builder,
            "task_options": {"k": "v"},
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://example.com",
        },
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=None,
    )
    result = run_create_file_operation(request)
    assert result.status == "generated"
    assert called == {"heartbeat": 1, "text": 1, "prompt": 1}


def test_insert_operation_prefers_dependencies_over_context(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("const a = 1;\n// ANCHOR\nconst b = 2;\n", encoding="utf-8")

    def _good_heartbeat(_options, _label, fn, timeout_seconds=60):
        _ = timeout_seconds
        return fn(), False

    def _good_generate_text(**_kwargs):
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        }

    deps = OperationDependencies(
        run_with_provider_heartbeat=_good_heartbeat,
        generate_text=_good_generate_text,
        build_insert_after_prompt=lambda **kwargs: "prompt",
        task_options={"k": "v"},
        api_key_env="OPENAI_API_KEY",
        base_url="https://example.com",
    )
    request = OperationRequest(
        contract=normalize_operation_contract(
            operation="insert-after",
            target_file="src/helpers.js",
            anchor="// ANCHOR",
            source="cli",
        ),
        task="insert helper",
        cwd=tmp_path,
        context={
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "failure_context": {"files": []},
            "run_with_provider_heartbeat": lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("context heartbeat should not run")),
            "generate_text": lambda **kwargs: (_ for _ in ()).throw(AssertionError("context generate_text should not run")),
            "build_insert_after_prompt": lambda **kwargs: (_ for _ in ()).throw(AssertionError("context prompt builder should not run")),
            "insert_original_text": "const a = 1;\n// ANCHOR\nconst b = 2;\n",
            "insert_anchor_index": 1,
        },
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )
    result = run_insert_after_operation(request)
    assert result.status == "generated"
    assert bool(result.diff_text)


def test_replace_block_operation_falls_back_to_context_when_dependencies_missing(tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    called: dict[str, int] = {"heartbeat": 0, "text": 0, "prompt": 0}

    def _context_heartbeat(_options, _label, fn, timeout_seconds=60):
        _ = timeout_seconds
        called["heartbeat"] += 1
        return fn(), False

    def _context_generate_text(**_kwargs):
        called["text"] += 1
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"NEW BLOCK"}',
            "error": None,
        }

    def _context_prompt_builder(**_kwargs):
        called["prompt"] += 1
        return "prompt"

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
            "run_with_provider_heartbeat": _context_heartbeat,
            "generate_text": _context_generate_text,
            "build_replace_block_prompt": _context_prompt_builder,
            "task_options": {"k": "v"},
            "api_key_env": "OPENAI_API_KEY",
            "base_url": "https://example.com",
        },
        failures={},
        patch_plan={"allowed_targets": ["src/helpers.js"]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=None,
    )
    result = run_replace_block_operation(request)
    assert result.status == "generated"
    assert called == {"heartbeat": 1, "text": 1, "prompt": 1}
