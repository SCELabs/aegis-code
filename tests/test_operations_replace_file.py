from __future__ import annotations

from pathlib import Path

from aegis_code.operations import OperationDependencies, OperationRequest, normalize_operation_contract
from aegis_code.operations import replace_file as replace_file_ops


def _request(tmp_path: Path, *, target_file: str) -> OperationRequest:
    deps = OperationDependencies(
        run_with_provider_heartbeat=lambda _options, _label, fn, timeout_seconds=60: (fn(), False),
        generate_text=lambda **_kwargs: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export function add(a, b) {\\n  if (!Number.isFinite(a) || !Number.isFinite(b)) return 0;\\n  return a + b;\\n}\\n"}',
            "error": None,
        },
        build_replace_file_prompt=lambda **_kwargs: "prompt",
        task_options={},
    )
    return OperationRequest(
        contract=normalize_operation_contract(
            operation="replace-file",
            target_file=target_file,
            allow_deletions=True,
            source="cli",
        ),
        task="rewrite file",
        cwd=tmp_path,
        context={"provider": "openai", "model": "gpt-4.1-mini", "failure_context": {"files": []}},
        failures={},
        patch_plan={"allowed_targets": [target_file]},
        aegis_execution={},
        model="gpt-4.1-mini",
        dependencies=deps,
    )


def test_parse_replace_file_provider_response_valid_json() -> None:
    ok, content, err = replace_file_ops._parse_replace_file_provider_response('{"content":"x\\n"}')
    assert ok is True
    assert content == "x\n"
    assert err is None


def test_parse_replace_file_provider_response_invalid_json() -> None:
    ok, content, err = replace_file_ops._parse_replace_file_provider_response("```json\n{\"content\":\"x\"}\n```")
    assert ok is False
    assert content is None
    assert err == "replace_file_output_invalid"


def test_replace_file_operation_generates_full_file_diff(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function add(a, b) { return a + b; }\n", encoding="utf-8")
    result = replace_file_ops.run_replace_file_operation(_request(tmp_path, target_file="src/notes.js"))
    assert result.status == "generated"
    assert "-export function add(a, b) { return a + b; }" in result.diff_text
    assert "+export function add(a, b) {" in result.diff_text


def test_replace_file_operation_allows_empty_content(tmp_path: Path) -> None:
    target = tmp_path / "src" / "notes.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export const x = 1;\n", encoding="utf-8")
    request = _request(tmp_path, target_file="src/notes.js")
    assert request.dependencies is not None
    request.dependencies.generate_text = lambda **_kwargs: {
        "available": True,
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "text": '{"content":""}',
        "error": None,
    }
    result = replace_file_ops.run_replace_file_operation(request)
    assert result.status == "generated"
    assert "-export const x = 1;" in result.diff_text


def test_replace_file_operation_target_missing(tmp_path: Path) -> None:
    result = replace_file_ops.run_replace_file_operation(_request(tmp_path, target_file="src/missing.js"))
    assert result.status == "unavailable"
    assert result.error == "operation_target_missing"
