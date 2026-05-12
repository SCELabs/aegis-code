from __future__ import annotations

import json
import types
from pathlib import Path

from aegis_code.models import AegisDecision, CommandResult
from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.policy import _is_additive_task, _js_exported_symbol_names, hard_invalid_content_evaluate
from aegis_code.report import render_markdown_report
from aegis_code.runtime import TaskOptions, _compute_apply_safety, build_run_payload, run_task
from tests.helpers import (
    command_result_from_output,
    pytest_output_fail,
    pytest_output_pass,
    retry_sequence_fail_then_fail,
    retry_sequence_fail_then_pass,
)


class _CapturingClient:
    def __init__(self) -> None:
        self.last_symptoms: list[str] = []
        self.last_metadata: dict[str, object] = {}
        self.decision = AegisDecision(
            model_tier="mid",
            context_mode="focused",
            max_retries=0,
            allow_escalation=False,
            execution={"budget": {"pressure": "low"}},
        )

    def step_scope(self, **kwargs: object) -> AegisDecision:
        symptoms = kwargs.get("symptoms", [])
        if isinstance(symptoms, list):
            self.last_symptoms = [str(item) for item in symptoms]
        metadata = kwargs.get("metadata", {})
        if isinstance(metadata, dict):
            self.last_metadata = metadata
        return self.decision


def _write_latest_runtime(cwd: Path, payload: dict[str, object]) -> None:
    runs = cwd / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_runtime_calls_aegis_after_observation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.analyze_failures_sll",
        lambda _text: {
            "available": True,
            "regime": "chaotic",
            "collapse_risk": 0.9,
            "fragmentation_risk": 0.8,
            "drift_risk": 0.7,
            "stable_random_risk": 0.95,
        },
    )
    client = _CapturingClient()
    payload = build_run_payload(
        options=TaskOptions(task="fix tests"),
        cwd=tmp_path,
        client=client,
    )

    assert payload["sll_analysis"]["available"] is True
    assert client.last_metadata["failure_count"] == 1
    assert client.last_metadata["command_status"] == "failed"
    assert client.last_metadata["initial_test_exit_code"] == 1
    assert "fragmented_output" in client.last_symptoms
    assert "degenerate_loop" in client.last_symptoms
    assert "unstable_workflow" in client.last_symptoms
    assert "ungrounded_output" in client.last_symptoms
    for key in ("attempted", "available", "provider", "model", "path", "error", "preview"):
        assert key in payload["patch_diff"]


def test_runtime_explicit_append_not_skipped_by_repeated_failure(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_old():\n    assert True\n", encoding="utf-8")
    _write_latest_runtime(
        tmp_path,
        {
            "status": "completed_tests_failed",
            "patch_diff": {"attempted": True, "available": True},
            "initial_failures": {
                "failure_count": 1,
                "failed_tests": [
                    {
                        "test_name": "tests/test_x.py::test_a",
                        "file": "tests/test_x.py",
                        "error": "AssertionError: x",
                    }
                ],
            },
            "final_failures": {
                "failure_count": 1,
                "failed_tests": [
                    {
                        "test_name": "tests/test_x.py::test_a",
                        "file": "tests/test_x.py",
                        "error": "AssertionError: x",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": "not-json",
            "error": None,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="add tests for todo CLI",
            propose_patch=True,
            command="patch",
            patch_operation="append",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["tests/test_cli.py"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["append"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("status") != "skipped_provider"
    assert payload.get("skip_reason") != "repeated_failure"
    assert payload["patch_diff"]["attempted"] is True
    assert payload["patch_diff"]["error"] == "append_output_invalid"


def test_runtime_create_file_bypasses_structured_controller_and_preserves_operation_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured controller should not run for create-file")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export function hasNotes(notes) { return notes.length > 0; }\\n"}',
            "error": None,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run for create-file")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run for create-file")),
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="create helper functions for notes",
            propose_patch=True,
            command="patch",
            patch_operation="create-file",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": True,
                "allowed_operations": ["create-file"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"].get("error") not in {"structured_output_invalid", "unsupported_mode"}
    assert payload["patch_operation"]["operation"] == "create-file"
    assert payload["patch_operation"]["source"] == "cli"


def test_runtime_create_file_dispatch_uses_scope_contract_operation_when_patch_operation_missing(
    monkeypatch, tmp_path: Path
) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured controller should not run for create-file")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export function hasNotes(notes) { return notes.length > 0; }\\n"}',
            "error": None,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run for create-file")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run for create-file")),
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="create helper functions for notes",
            propose_patch=True,
            command="patch",
            patch_operation=None,
            scope_contract={
                "source": "cli_explicit",
                "operation": "create-file",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": True,
                "allowed_operations": ["create-file"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"].get("error") not in {"structured_output_invalid", "unsupported_mode"}
    assert payload["patch_operation"]["operation"] == "create-file"
    assert payload["patch_operation"]["source"] == "cli"


def test_runtime_insert_after_uses_generate_text_and_preserves_metadata(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("const a = 1;\n// ANCHOR\nconst b = 2;\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured controller should not run for insert-after")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run for insert-after")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"export function hasNotes(notes) { return notes.length > 0; }\\n"}',
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="insert helper",
            propose_patch=True,
            command="patch",
            patch_operation="insert-after",
            anchor="// ANCHOR",
            scope_contract={
                "source": "cli_explicit",
                "operation": "insert-after",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["insert-after"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["error"] not in {"structured_output_invalid", "unsupported_mode"}
    assert payload["patch_operation"]["operation"] == "insert-after"
    assert payload["patch_operation"]["source"] == "cli"


def test_runtime_insert_after_missing_anchor_blocks_contract(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("const a = 1;\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.generate_text", lambda **_: (_ for _ in ()).throw(AssertionError("provider should not run")))
    payload = build_run_payload(
        options=TaskOptions(
            task="insert helper",
            propose_patch=True,
            command="patch",
            patch_operation="insert-after",
            anchor=None,
            scope_contract={
                "source": "cli_explicit",
                "operation": "insert-after",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["insert-after"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "operation_contract_invalid"


def test_runtime_insert_after_anchor_not_found_blocks(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("const a = 1;\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        },
    )
    monkeypatch.setattr("aegis_code.runtime.generate_structured_edits", lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run")))
    payload = build_run_payload(
        options=TaskOptions(
            task="insert helper",
            propose_patch=True,
            command="patch",
            patch_operation="insert-after",
            anchor="MISSING",
            scope_contract={
                "source": "cli_explicit",
                "operation": "insert-after",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["insert-after"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "operation_anchor_not_found"
    assert payload["patch_diff"]["error"] not in {"structured_output_invalid", "unsupported_mode"}


def test_runtime_insert_after_with_anchor_does_not_fall_back_to_contract_invalid(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function completeNote() {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run for insert-after")),
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="insert helper",
            propose_patch=True,
            command="patch",
            patch_operation="insert-after",
            anchor="DOES_NOT_EXIST",
            scope_contract={
                "source": "cli_explicit",
                "operation": "insert-after",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["insert-after"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "operation_anchor_not_found"
    assert payload["patch_diff"]["error"] != "operation_contract_invalid"


def test_runtime_insert_after_uses_scope_anchor_when_options_anchor_missing(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "src" / "helpers.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("export function completeNote() {}\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_text",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"inserted line\\n"}',
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="insert helper",
            propose_patch=True,
            command="patch",
            patch_operation="insert-after",
            anchor=None,
            scope_contract={
                "source": "cli_explicit",
                "operation": "insert-after",
                "anchor": "DOES_NOT_EXIST",
                "allowed_targets": ["src/helpers.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["insert-after"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "operation_anchor_not_found"


def test_runtime_sll_active_failure_path_maps_expected_symptoms_and_metadata(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.analyze_failures_sll",
        lambda _text: {
            "available": True,
            "regime": "fragmentation",
            "fragmentation_risk": 0.9,
            "collapse_risk": 0.0,
            "drift_risk": 0.7,
            "stable_random_risk": 0.0,
        },
    )
    client = _CapturingClient()
    payload = build_run_payload(options=TaskOptions(task="sll active"), cwd=tmp_path, client=client)

    assert payload["failures"]["failure_count"] > 0
    assert client.last_metadata["failure_count"] == 1
    assert client.last_metadata["command_status"] == "failed"
    assert client.last_metadata["initial_test_exit_code"] == 1
    assert client.last_metadata["sll_available"] is True
    assert client.last_metadata["sll_regime"] == "fragmentation"
    assert client.last_symptoms == ["unstable_workflow", "test_failure", "fragmented_output"]


def test_retry_loop_success_after_retry(monkeypatch, tmp_path: Path) -> None:
    results = retry_sequence_fail_then_pass()

    def _fake_run(_cmd: str, cwd=None) -> CommandResult:
        return results.pop(0)

    monkeypatch.setattr("aegis_code.runtime.run_configured_tests", _fake_run)
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    client = _CapturingClient()
    client.decision = AegisDecision(
        model_tier="mid",
        context_mode="focused",
        max_retries=2,
        allow_escalation=True,
        execution={"budget": {"pressure": "low"}},
    )
    payload = build_run_payload(options=TaskOptions(task="retry test"), cwd=tmp_path, client=client)

    assert payload["status"] == "completed_tests_passed_after_retry"
    assert len(payload["test_attempts"]) == 2
    assert payload["retry_policy"]["retry_attempted"] is True
    assert payload["retry_policy"]["retry_count"] == 1
    assert payload["retry_policy"]["stopped_reason"] == "passed_after_retry"
    assert "No patch required after retry success" in payload["patch_plan"]["strategy"]


def test_retry_loop_no_retry_without_permission(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    client = _CapturingClient()
    client.decision = AegisDecision(
        model_tier="mid",
        context_mode="focused",
        max_retries=2,
        allow_escalation=False,
        execution={},
    )
    payload = build_run_payload(options=TaskOptions(task="no retry test"), cwd=tmp_path, client=client)

    assert len(payload["test_attempts"]) == 1
    assert payload["retry_policy"]["retry_attempted"] is False
    assert payload["retry_policy"]["stopped_reason"] == "retry_not_allowed"
    assert payload["status"] == "completed_tests_failed"


def test_retry_loop_initial_pass_no_retry(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.resolve_verification_command",
        lambda _cwd: {
            "available": True,
            "command": "python -m pytest -q",
            "source": "config",
            "observed": True,
        },
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(
        model_tier="mid",
        context_mode="focused",
        max_retries=2,
        allow_escalation=True,
        execution={},
    )

    payload = build_run_payload(options=TaskOptions(task="initial pass"), cwd=tmp_path, client=client)
    assert payload["status"] == "completed_tests_passed"
    assert len(payload["test_attempts"]) == 1
    assert payload["retry_policy"]["retry_attempted"] is False
    assert payload["retry_policy"]["stopped_reason"] == "initial_passed"
    assert payload["patch_plan"]["proposed_changes"] == []
    assert payload["patch_plan"]["confidence"] >= 0.9


def test_retry_loop_fails_after_max_retries(monkeypatch, tmp_path: Path) -> None:
    results = retry_sequence_fail_then_fail()

    def _fake_run(_cmd: str, cwd=None) -> CommandResult:
        return results.pop(0)

    monkeypatch.setattr("aegis_code.runtime.run_configured_tests", _fake_run)
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(
        model_tier="mid",
        context_mode="focused",
        max_retries=2,
        allow_escalation=True,
        execution={},
    )

    payload = build_run_payload(options=TaskOptions(task="always fail"), cwd=tmp_path, client=client)
    assert payload["status"] == "completed_tests_failed_after_retry"
    assert len(payload["test_attempts"]) == 3
    assert payload["retry_policy"]["retry_count"] == 2
    assert payload["retry_policy"]["stopped_reason"] == "max_retries_exhausted"
    assert payload["patch_plan"]["proposed_changes"]


def test_runtime_aegis_unavailable_still_reports(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(
        model_tier="mid",
        context_mode="focused",
        max_retries=1,
        allow_escalation=False,
        execution={"status": "unavailable"},
    )

    payload = run_task(options=TaskOptions(task="aegis unavailable"), cwd=tmp_path, client=client)
    assert payload["status"] == "completed_tests_failed"
    assert len(payload["test_attempts"]) == 1
    assert (tmp_path / ".aegis" / "runs" / "latest.md").exists()


def test_runtime_no_test_command_marks_unverified_and_skips_patch_diff(tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "\n".join(
            [
                "mode: balanced",
                "budget_per_task: 1.0",
                "models:",
                "  cheap: openai:gpt-4.1-nano",
                "  mid: openai:gpt-4.1-mini",
                "  premium: openai:gpt-4.1",
                "commands:",
                '  test: ""',
                '  lint: ""',
                "aegis:",
                '  base_url: "http://example.test"',
                "providers:",
                "  enabled: false",
                '  provider: "openai"',
                '  api_key_env: "OPENAI_API_KEY"',
                "patches:",
                "  generate_diff: false",
                "  max_context_chars: 12000",
                '  output_file: ".aegis/runs/latest.diff"',
            ]
        ),
        encoding="utf-8",
    )
    client = _CapturingClient()
    payload = build_run_payload(options=TaskOptions(task="no command", propose_patch=True), cwd=tmp_path, client=client)
    assert payload["status"] == "completed_no_commands"
    assert payload["verification"]["available"] is False
    assert payload["verification"]["test_command"] is None
    assert payload["verification"]["source"] == "none"
    assert payload["verification"]["observed"] is False
    assert payload["test_attempts"] == []
    assert payload["failures"]["failure_count"] == 0
    assert payload["patch_diff"]["attempted"] is False
    assert payload["patch_quality"] is None


def test_runtime_local_default_passing_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = run_task(options=TaskOptions(task="local pass"), cwd=tmp_path, client=_CapturingClient())
    assert payload["status"] == "completed_tests_passed"


def test_runtime_propose_patch_provider_dependency_missing_sets_provider_unavailable_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.should_skip_provider", lambda _o, _c: {"skip": False, "reason": "none", "action": None})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "openai package is not installed.",
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add helper function", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    assert payload["patch_diff"]["attempted"] is True
    assert payload["patch_diff"]["available"] is False
    assert "openai package is not installed" in str(payload["patch_diff"]["error"])
    assert payload["status"] == "completed_provider_unavailable"


def test_runtime_local_default_failing_status(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = run_task(options=TaskOptions(task="local fail"), cwd=tmp_path, client=_CapturingClient())
    assert payload["status"] == "completed_tests_failed"


def test_runtime_payload_includes_verification_source_and_observed(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text('commands:\n  test: ""\n', encoding="utf-8")
    (tmp_path / ".aegis" / "capabilities.json").write_text(
        json.dumps({"test_command": "pytest -q", "test_command_observed": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(options=TaskOptions(task="verify source"), cwd=tmp_path, client=_CapturingClient())
    assert payload["verification"]["command"] == "pytest -q"
    assert payload["verification"]["source"] == "capabilities"
    assert payload["verification"]["observed"] is True


def test_runtime_uses_configured_command_over_observed_capabilities(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    configured = ".venv/Scripts/python.exe -m pytest -q"
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        f'commands:\n  test: "{configured}"\n',
        encoding="utf-8",
    )
    (tmp_path / ".aegis" / "capabilities.json").write_text(
        json.dumps({"test_command": "pytest -q", "test_command_observed": True}),
        encoding="utf-8",
    )
    seen: list[str] = []

    def _capture(cmd: str, cwd=None) -> CommandResult:
        seen.append(cmd)
        return command_result_from_output(pytest_output_pass(), status="ok", exit_code=0, command=cmd)

    monkeypatch.setattr("aegis_code.runtime.run_configured_tests", _capture)
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(options=TaskOptions(task="verify configured command"), cwd=tmp_path, client=_CapturingClient())
    assert seen == [configured]
    assert payload["verification"]["command"] == configured
    assert payload["verification"]["source"] == "config"
    assert payload["verification"]["observed"] is False


def test_runtime_payload_includes_sll_pre_call_and_risk(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.should_skip_provider", lambda _o, _c: {"skip": False, "reason": "none", "action": None})
    monkeypatch.setattr(
        "aegis_code.runtime.run_sll_analysis",
        lambda _text: {
            "available": True,
            "regime": "boundary",
            "coherence": 0.7,
            "collapse_risk": 0.2,
            "fragmentation_risk": 0.6,
            "drift_risk": 0.1,
            "recommendation": None,
        },
    )
    monkeypatch.setattr("aegis_code.runtime.classify_sll_risk", lambda _data: "watch")
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {"available": False, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": "x"},
    )
    payload = build_run_payload(options=TaskOptions(task="sll payload", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    assert payload["sll_pre_call"]["available"] is True
    assert payload["sll_risk"] == "watch"


def test_runtime_no_crash_when_sll_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.should_skip_provider", lambda _o, _c: {"skip": False, "reason": "none", "action": None})
    monkeypatch.setattr("aegis_code.runtime.run_sll_analysis", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {"available": False, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": "x"},
    )
    payload = build_run_payload(options=TaskOptions(task="sll missing", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    assert payload["sll_pre_call"]["available"] is False
    assert payload["sll_risk"] == "low"


def test_runtime_payload_includes_sll_fix_guidance_after_failure(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.should_skip_provider", lambda _o, _c: {"skip": False, "reason": "none", "action": None})
    monkeypatch.setattr(
        "aegis_code.runtime.run_sll_analysis",
        lambda _text: {
            "available": True,
            "regime": "fragmentation",
            "coherence": 0.2,
            "collapse_risk": 0.2,
            "fragmentation_risk": 0.9,
            "drift_risk": 0.1,
            "recommendation": None,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {"available": False, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": "x"},
    )
    payload = build_run_payload(options=TaskOptions(task="sll fix guidance", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    assert payload["sll_fix_guidance"]["strategy"] == "narrow_scope"


def test_prompt_includes_sll_guidance_only_in_fix_loop_regeneration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.should_skip_provider", lambda _o, _c: {"skip": False, "reason": "none", "action": None})
    monkeypatch.setattr(
        "aegis_code.runtime.run_sll_analysis",
        lambda _text: {
            "available": True,
            "regime": "fragmentation",
            "coherence": 0.2,
            "collapse_risk": 0.2,
            "fragmentation_risk": 0.9,
            "drift_risk": 0.1,
            "recommendation": None,
        },
    )
    calls: list[dict[str, object]] = []

    def _provider(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        if len(calls) == 1:
            return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    _ = build_run_payload(options=TaskOptions(task="regen with guidance", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    assert len(calls) >= 2
    assert calls[0].get("sll_guidance") is None
    second = calls[1].get("sll_guidance")
    assert isinstance(second, dict)
    assert second.get("strategy") == "narrow_scope"


def test_runtime_payload_includes_project_context_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    payload = build_run_payload(
        options=TaskOptions(
            task="context metadata",
            project_context={
                "available": True,
                "included_paths": [".aegis/context/project_summary.md"],
                "total_chars": 88,
                "files": {"project_summary": "ignored"},
            },
        ),
        cwd=tmp_path,
        client=client,
    )
    assert payload["project_context"]["available"] is True
    assert payload["project_context"]["included_paths"] == [".aegis/context/project_summary.md"]
    assert payload["project_context"]["total_chars"] == 88
    assert payload["project_context"]["secret_values_exposed"] is False
    assert isinstance(payload["project_context"]["available_project_keys"], list)
    assert isinstance(payload["project_context"]["available_global_keys"], list)


def test_runtime_passes_repo_map_into_provider_context(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    captured: dict[str, object] = {}

    def _provider(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"available": False, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": "x"}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    _ = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_CapturingClient())
    context = captured.get("context")
    assert isinstance(context, dict)
    assert isinstance(context.get("repo_map"), dict)
    assert "rendered" in context.get("repo_map")


def test_runtime_passes_repo_map_into_append_context(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_old():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    captured: dict[str, object] = {}

    def _structured(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"\\n\\ndef test_more():\\n    assert 1 == 1\\n"}',
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_structured_edits", _structured)
    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run")))
    _ = build_run_payload(
        options=TaskOptions(
            task="add tests for cli",
            propose_patch=True,
            command="patch",
            patch_operation="append",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["tests/test_cli.py"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["append"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    context = captured.get("context")
    assert isinstance(context, dict)
    assert isinstance(context.get("repo_map"), dict)
    append_ctx = context.get("append_target_contexts")
    assert isinstance(append_ctx, list) and append_ctx
    first = append_ctx[0]
    assert isinstance(first, dict)
    assert str(first.get("path")) == "tests/test_cli.py"
    assert "existing_names" in first
    assert "imports" in first
    snippets = context.get("relevant_file_snippets")
    assert isinstance(snippets, list)


def test_runtime_payload_includes_budget_state_and_runtime_policy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    payload = build_run_payload(
        options=TaskOptions(
            task="control payload",
            budget_state={
                "available": True,
                "limit": 1.0,
                "spent_estimate": 0.2,
                "remaining_estimate": 0.8,
            },
            runtime_policy={
                "requested_mode": "balanced",
                "selected_mode": "balanced",
                "reason": "default",
                "budget_present": True,
                "context_available": True,
            },
        ),
        cwd=tmp_path,
        client=client,
    )
    assert payload["budget_state"]["available"] is True
    assert payload["budget_state"]["remaining_estimate"] == 0.8
    assert payload["runtime_policy"]["requested_mode"] == "balanced"
    assert payload["runtime_policy"]["selected_mode"] == "balanced"
    assert payload["runtime_policy"]["reason"] == "default"


def test_aegis_guidance_overrides_model_tier(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=1, allow_escalation=True, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="tier override", aegis_guidance={"model_tier": "cheap"}),
        cwd=tmp_path,
        client=client,
    )
    assert payload["selected_model_tier"] == "cheap"
    assert payload["applied_aegis_guidance"]["model_tier_override"] == "cheap"


def test_aegis_guidance_caps_max_retries(monkeypatch, tmp_path: Path) -> None:
    results = retry_sequence_fail_then_fail()

    def _fake_run(_cmd: str, cwd=None) -> CommandResult:
        return results.pop(0)

    monkeypatch.setattr("aegis_code.runtime.run_configured_tests", _fake_run)
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=2, allow_escalation=True, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="retry cap", aegis_guidance={"max_retries": 1}),
        cwd=tmp_path,
        client=client,
    )
    assert payload["retry_policy"]["max_retries"] == 1
    assert payload["retry_policy"]["retry_count"] == 1


def test_aegis_guidance_disables_escalation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=2, allow_escalation=True, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="no escalation", aegis_guidance={"allow_escalation": False}),
        cwd=tmp_path,
        client=client,
    )
    assert payload["retry_policy"]["allow_escalation"] is False
    assert payload["retry_policy"]["retry_attempted"] is False


def test_no_aegis_guidance_keeps_behavior(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=2, allow_escalation=True, execution={})
    payload = build_run_payload(options=TaskOptions(task="unchanged"), cwd=tmp_path, client=client)
    assert payload["selected_model_tier"] == "mid"
    assert payload["retry_policy"]["max_retries"] == 2


def test_cheapest_mode_forces_cheap_model_tier(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=1, allow_escalation=False, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="cheap mode", mode="cheapest"),
        cwd=tmp_path,
        client=client,
    )
    assert payload["selected_model_tier"] == "cheap"


def test_apply_safety_scoring() -> None:
    assert _compute_apply_safety(validation_valid=False, syntactic_valid=True, plan_consistent=True, confidence=0.99) == "BLOCKED"
    assert _compute_apply_safety(validation_valid=True, syntactic_valid=False, plan_consistent=True, confidence=0.99) == "BLOCKED"
    assert _compute_apply_safety(validation_valid=True, syntactic_valid=True, plan_consistent=False, confidence=0.99) == "BLOCKED"
    assert _compute_apply_safety(validation_valid=True, syntactic_valid=True, plan_consistent=True, confidence=0.90) == "HIGH"
    assert _compute_apply_safety(validation_valid=True, syntactic_valid=True, plan_consistent=True, confidence=0.70) == "MEDIUM"
    assert _compute_apply_safety(validation_valid=True, syntactic_valid=True, plan_consistent=True, confidence=0.69) == "LOW"


def test_balanced_mode_keeps_mid_model_tier(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=1, allow_escalation=False, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="balanced mode", mode="balanced"),
        cwd=tmp_path,
        client=client,
    )
    assert payload["selected_model_tier"] == "mid"


def test_aegis_guidance_override_wins_over_cheapest_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    client = _CapturingClient()
    client.decision = AegisDecision(model_tier="mid", context_mode="focused", max_retries=1, allow_escalation=False, execution={})
    payload = build_run_payload(
        options=TaskOptions(task="guidance priority", mode="cheapest", aegis_guidance={"model_tier": "premium"}),
        cwd=tmp_path,
        client=client,
    )
    assert payload["selected_model_tier"] == "premium"


def test_relevant_snippet_extraction_is_deterministic_and_bounded(tmp_path: Path) -> None:
    from aegis_code.runtime import _build_relevant_file_snippets

    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text(
        "import argparse\nCONSTANT_VALUE = 'hello'\n\ndef main():\n    print('run')\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "helpers.py").write_text(
        "\n".join(f"def helper_{idx}():\n    return {idx}" for idx in range(180)),
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    patch_plan = {"allowed_targets": ["src/main.py"], "proposed_changes": [{"file": "src/helpers.py"}]}
    context = {"files": [{"path": "tests/test_main.py", "content": "def test_main():\n    assert True\n"}]}
    repo_map = {
        "source_files": [{"path": "src/main.py"}, {"path": "src/helpers.py"}],
        "test_files": [{"path": "tests/test_main.py"}],
        "cli_hints": {"main_function_files": ["src/main.py"]},
    }
    first = _build_relevant_file_snippets(cwd=tmp_path, patch_plan=patch_plan, failure_context=context, repo_map=repo_map)
    second = _build_relevant_file_snippets(cwd=tmp_path, patch_plan=patch_plan, failure_context=context, repo_map=repo_map)
    assert first == second
    assert first
    assert len(first) <= 6
    assert all(len(str(item.get("excerpt", ""))) <= 900 for item in first)
    assert sum(len(str(item.get("excerpt", ""))) for item in first) <= 3600


def test_runtime_accepts_calculator_source_repair_with_fix_scope(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from src.calculator import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
        encoding="utf-8",
    )
    fail_output = (
        "=================================== FAILURES ===================================\n"
        "___________________________________ test_add ___________________________________\n"
        "E       assert 0 == 2\n"
        "tests/test_calculator.py:4: AssertionError\n"
        "FAILED tests/test_calculator.py::test_add - AssertionError\n"
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(fail_output, status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: {"attempted": True, "status": "skipped", "available": False, "failure_reason": "provider_unavailable"},
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/calculator.py b/src/calculator.py\n"
                "--- a/src/calculator.py\n"
                "+++ b/src/calculator.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def add(a, b):\n"
                "-    return a - b\n"
                "+    return a + b\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="fix failing tests in tests/test_calculator.py",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src\\calculator.py", "tests\\test_calculator.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    patch_diff = payload.get("patch_diff", {})
    assert patch_diff.get("available") is True
    assert patch_diff.get("plan_consistent") is True
    assert patch_diff.get("plan_missing_targets") == []
    checked = check_patch_text((tmp_path / ".aegis" / "runs" / "latest.diff").read_text(encoding="utf-8"), cwd=tmp_path)
    assert checked["valid"] is True
    assert checked["apply_blocked"] is False


def test_runtime_outside_allowed_targets_emits_target_diagnostics(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: {
            "attempted": True,
            "available": False,
            "status": "failed",
            "failure_reason": "outside_allowed_targets",
            "errors": ["invalid_path:outside_allowed_targets"],
            "retry_attempted": True,
            "retry_count": 1,
            "target_diagnostics": {
                "raw_edit_paths": ["src\\calculator.py"],
                "normalized_edit_paths": ["src/calculator.py"],
                "raw_allowed_targets": ["src/calculator.py", "tests/test_calculator.py"],
                "normalized_allowed_targets": ["src/calculator.py", "tests/test_calculator.py"],
                "validator_source": "structured_edits",
            },
        },
    )
    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run")))
    payload = build_run_payload(
        options=TaskOptions(
            task="fix failing tests in tests/test_calculator.py",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/calculator.py", "tests/test_calculator.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    patch_diff = payload.get("patch_diff", {})
    assert patch_diff.get("status") == "blocked"
    assert payload.get("structured_patch", {}).get("failure_reason") == "outside_allowed_targets"
    diagnostics = patch_diff.get("target_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("validator_source") == "structured_edits"


def test_feature_plan_multi_file_patch_ordering_and_payload(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "b.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(
            task="update feature across files",
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/b.py", "tests/test_a.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
            propose_patch=False,
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    feature_plan = payload.get("feature_plan")
    assert isinstance(feature_plan, dict)
    assert feature_plan.get("available") is True
    steps = feature_plan.get("steps", [])
    assert isinstance(steps, list)
    assert [item.get("target_file") for item in steps] == ["src/b.py", "tests/test_a.py"]
    assert [item.get("id") for item in steps] == ["step_1", "step_2"]
    assert all(item.get("operation") == "replace" for item in steps)
    assert all(item.get("status") == "planned" for item in steps)
    assert all(int(item.get("max_changed_lines", 0)) == 300 for item in steps)


def test_feature_plan_single_file_patch_unchanged(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "only.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(
            task="single file patch",
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/only.py"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
            propose_patch=False,
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("feature_plan") is None


def test_feature_plan_append_unchanged(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(
            task="append docs",
            command="patch",
            patch_operation="append",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["README.md"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["append"],
                "missing_targets": [],
                "block_reason": None,
            },
            propose_patch=False,
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("feature_plan") is None


def test_feature_plan_successful_three_step_flow(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("VALUE_A = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("VALUE_B = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_c.py").write_text("def test_c():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        file_path = cwd / target
        old_text = file_path.read_text(encoding="utf-8")
        if target.endswith("a.py"):
            new_text = old_text.replace("1", "2")
        elif target.endswith("b.py"):
            new_text = old_text.replace("1", "3")
        else:
            new_text = old_text + "\n# touched\n"
        from difflib import unified_diff
        diff_body = "\n".join(
            unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile=f"a/{target}",
                tofile=f"b/{target}",
                lineterm="",
            )
        )
        diff_text = f"diff --git a/{target} b/{target}\n{diff_body}\n"
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=diff_text, files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="implement feature",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/a.py", "src/b.py", "tests/test_c.py"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("patch_diff", {}).get("status") == "generated"
    diff_path = Path(str(payload.get("patch_diff", {}).get("path", "")))
    assert diff_path.exists()
    checked = check_patch_text(diff_path.read_text(encoding="utf-8"), cwd=tmp_path)
    assert checked["valid"] is True
    files = checked.get("files", [])
    touched = sorted(
        {
            str(item.get("new_path") or item.get("old_path"))
            for item in files
            if isinstance(item, dict)
        }
    )
    assert touched == ["src/a.py", "src/b.py", "tests/test_c.py"]


def test_feature_plan_per_step_scope_enforced(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    seen_targets: list[str] = []

    def _controller(*, contract, cwd, **_kwargs):
        assert len(contract.allowed_targets) == 1
        target = str(contract.allowed_targets[0])
        seen_targets.append(target)
        file_path = cwd / target
        old_text = file_path.read_text(encoding="utf-8")
        new_text = old_text.replace("1", "2")
        from difflib import unified_diff
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="multi scope",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/a.py", "src/b.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("patch_diff", {}).get("status") == "generated"
    assert seen_targets == ["src/a.py", "src/b.py"]


def test_feature_plan_step_failure_blocks_entire_feature(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("B = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        if target.endswith("b.py"):
            return {
                "attempted": True,
                "available": False,
                "status": "failed",
                "failure_reason": "outside_allowed_targets",
                "errors": ["invalid_path:outside_allowed_targets"],
                "retry_attempted": True,
                "retry_count": 1,
                "result": None,
                "provider_result": {},
                "target_diagnostics": {
                    "raw_edit_paths": ["src\\oops.py"],
                    "normalized_edit_paths": ["src/oops.py"],
                    "raw_allowed_targets": ["src/b.py"],
                    "normalized_allowed_targets": ["src/b.py"],
                    "validator_source": "structured_edits",
                },
            }
        from difflib import unified_diff
        old_text = (cwd / target).read_text(encoding="utf-8")
        new_text = old_text.replace("1", "2")
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="implement feature changes",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/a.py", "src/b.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("patch_diff", {}).get("status") == "blocked"
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_feature_plan_does_not_use_docs_wrapper_fallback(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime._maybe_wrap_docs_non_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("docs wrapper should not be used in feature plan mode")),
    )

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        from difflib import unified_diff
        old_text = (cwd / target).read_text(encoding="utf-8")
        new_text = old_text.replace("1", "2")
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="multi feature",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/a.py", "tests/test_a.py"],
                "max_files": 2,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload.get("patch_diff", {}).get("status") == "generated"


def test_feature_plan_activates_for_explicit_multi_file_patch_with_passing_verification(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime._maybe_wrap_docs_non_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("docs wrapper should not run")),
    )
    calls: list[str] = []

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        calls.append(target)
        from difflib import unified_diff
        old_text = (cwd / target).read_text(encoding="utf-8")
        if target.endswith("README.md"):
            new_text = old_text + "\n## Usage\n\n- Added usage example.\n"
        else:
            new_text = old_text + "\n# updated\n"
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="add POST /todos endpoint and tests",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["app/main.py", "tests/test_main.py", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert isinstance(payload.get("feature_plan"), dict)
    assert payload.get("patch_diff", {}).get("status") == "generated"
    assert calls == ["app/main.py", "tests/test_main.py", "README.md"]
    report = render_markdown_report(payload, cwd=tmp_path)
    assert "## Multi-file Feature Plan" in report


def test_feature_plan_touched_files_match_accepted_accumulated_diff(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        from difflib import unified_diff
        old_text = (cwd / target).read_text(encoding="utf-8")
        new_text = old_text + "\n# touched\n"
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="add POST /todos endpoint with request body validation, tests, and README usage example",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["app/main.py", "tests/test_main.py", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert sorted(payload["patch_diff"].get("touched_files", [])) == ["README.md", "app/main.py", "tests/test_main.py"]
    report = render_markdown_report(payload, cwd=tmp_path)
    assert "Files touched: `README.md, app/main.py, tests/test_main.py`" in report
    assert "src/module.py" not in report
    assert "tests/test_module.py" not in report


def test_fastapi_todo_flow_contract_coherent(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        if target == "app/main.py":
            new_text = (
                "from fastapi import FastAPI\n"
                "from pydantic import BaseModel\n"
                "from uuid import uuid4\n\n"
                "app = FastAPI()\n\n"
                "class TodoIn(BaseModel):\n"
                "    description: str\n\n"
                "@app.post('/todos')\n"
                "def create_todo(todo: TodoIn):\n"
                "    return {'id': str(uuid4()), 'description': todo.description}\n"
            )
        elif target == "tests/test_main.py":
            new_text = (
                "def test_create_todo_contract():\n"
                "    response = {'id': 'abc', 'description': 'buy milk'}\n"
                "    assert response['id']\n"
                "    assert response['description'] == 'buy milk'\n"
            )
        else:
            new_text = (
                "# Project\n\n"
                "## Usage\n\n"
                "POST /todos with {\"description\": \"buy milk\"} returns {\"id\": \"...\", \"description\": \"buy milk\"}\n"
            )
        old_text = (cwd / target).read_text(encoding="utf-8")
        from difflib import unified_diff
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="add POST /todos endpoint with request body validation, tests, and README usage example",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["app/main.py", "tests/test_main.py", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["error"] is None
    checked = check_patch_text(Path(str(payload["patch_diff"]["path"])).read_text(encoding="utf-8"), cwd=tmp_path)
    assert checked["valid"] is True


def test_readme_title_preserved_unless_explicitly_requested(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        if target == "README.md":
            new_text = "# Todo API\n\n## Usage\n\n- example\n"
        else:
            old_text = (cwd / target).read_text(encoding="utf-8")
            new_text = old_text + "\n# touched\n"
        old_text = (cwd / target).read_text(encoding="utf-8")
        from difflib import unified_diff
        diff_body = "\n".join(
            unified_diff(old_text.splitlines(), new_text.splitlines(), fromfile=f"a/{target}", tofile=f"b/{target}", lineterm="")
        )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=f"diff --git a/{target} b/{target}\n{diff_body}\n", files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload_blocked = build_run_payload(
        options=TaskOptions(
            task="add POST /todos endpoint with request body validation, tests, and README usage example",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["app/main.py", "tests/test_main.py", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload_blocked["patch_diff"]["status"] == "invalid"
    assert payload_blocked["patch_diff"]["error"] == "readme_title_changed"

    payload_allowed = build_run_payload(
        options=TaskOptions(
            task="add POST /todos endpoint and change README title to Todo API",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["app/main.py", "tests/test_main.py", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload_allowed["patch_diff"]["status"] == "generated"


def test_append_blocks_require_in_esm_js_target(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"notes","type":"module"}', encoding="utf-8")
    target = tmp_path / "tests" / "notes.test.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import test from 'node:test';\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "notes.js").write_text("export function addNote() { return 1; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"\\nconst x = require(\\"assert\\");\\n"}',
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="add test for deleteNote",
            propose_patch=True,
            command="patch",
            patch_operation="append",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["tests/notes.test.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["append"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "append_source_conflict"


def test_append_blocks_jest_style_when_node_test_detected(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "tests" / "notes.test.js"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("import test from 'node:test';\nimport assert from 'node:assert/strict';\n", encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "notes.js").write_text("export function addNote() { return 1; }\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "text": '{"content":"\\n\\ndescribe(\\"notes\\", () => {\\n  expect(1).toBe(1);\\n});\\n"}',
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="add test for deleteNote",
            propose_patch=True,
            command="patch",
            patch_operation="append",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["tests/notes.test.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["append"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "blocked"
    assert payload["patch_diff"]["error"] == "append_source_conflict"


def test_additive_source_rewrite_is_blocked(monkeypatch, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    target = src / "notes.js"
    target.write_text(
        "export function addNote() { return 1; }\n"
        "export function listNotes() { return []; }\n"
        "export default { addNote, listNotes };\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.run_structured_proposal_controller",
        lambda **_: {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(
                diff=(
                    "diff --git a/src/notes.js b/src/notes.js\n"
                    "--- a/src/notes.js\n"
                    "+++ b/src/notes.js\n"
                    "@@ -1,3 +1,1 @@\n"
                    "-export function addNote() { return 1; }\n"
                    "-export function listNotes() { return []; }\n"
                    "-export default { addNote, listNotes };\n"
                    "+export function deleteNote() { return 1; }\n"
                ),
                files=["src/notes.js"],
            ),
            "provider_result": {},
        },
    )
    payload = build_run_payload(
        options=TaskOptions(
            task="add deleteNote(notes, index)",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/notes.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "destructive_public_api_rewrite"


def test_js_additive_task_preserves_existing_exports(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "notes.js").write_text(
        "export function addNote() { return 1; }\n"
        "export function listNotes() { return []; }\n"
        "export function completeNote() { return true; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/notes.js b/src/notes.js\n"
                "--- a/src/notes.js\n"
                "+++ b/src/notes.js\n"
                "@@ -1,3 +1,2 @@\n"
                "-export function addNote() { return 1; }\n"
                "-export function listNotes() { return []; }\n"
                " export function completeNote() { return true; }\n"
                "+export function deleteNote() { return true; }\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add deleteNote(notes, index)", propose_patch=True),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "destructive_public_api_rewrite"


def test_python_additive_task_preserves_existing_public_functions(monkeypatch, tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "notes.py").write_text(
        "def add_note(text: str) -> str:\n    return text\n\n"
        "def list_notes() -> list[str]:\n    return []\n\n"
        "def complete_note(idx: int) -> bool:\n    return True\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/notes.py b/src/notes.py\n"
                "--- a/src/notes.py\n"
                "+++ b/src/notes.py\n"
                "@@ -1,7 +1,7 @@\n"
                "-def add_note(text: str) -> str:\n"
                "-    return text\n"
                "+def delete_note(notes: list[str], index: int) -> list[str]:\n"
                "+    return notes[:index] + notes[index+1:]\n"
                " def list_notes() -> list[str]:\n"
                "     return []\n"
                " def complete_note(idx: int) -> bool:\n"
                "     return True\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add delete_note(notes, index)", propose_patch=True),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "destructive_public_api_rewrite"


def test_js_readme_blocks_python_examples(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    (tmp_path / "README.md").write_text("# Notes\n\n## Summary\n\nJS notes app.\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -3,3 +3,9 @@\n"
                " ## Summary\n"
                " \n"
                " JS notes app.\n"
                "+\n"
                "+## Usage\n"
                "+\n"
                "+```python\n"
                "+def add_note(text):\n"
                "+    return text\n"
                "+```\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add README usage examples", propose_patch=True),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "docs_language_mismatch"


def test_readme_summary_rewrite_blocked_without_explicit_request(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Notes\n\n## Summary\n\nOriginal summary.\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -1,4 +1,4 @@\n"
                " # Notes\n"
                "-## Summary\n"
                "+## Overview\n"
                " \n"
                "-Original summary.\n"
                "+Rewritten summary.\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add README usage examples", propose_patch=True),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "destructive_docs_rewrite"


def test_multi_file_feature_bad_node_diff_is_blocked_by_policy(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"npm test\"\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"name":"notes","type":"module","scripts":{"test":"node --test"}}',
        encoding="utf-8",
    )
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text(
        "export function addNote(notes, text) { return [...notes, text]; }\n"
        "export function listNotes(notes) { return notes; }\n"
        "export function completeNote(notes, index) { return notes; }\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "notes.test.js").write_text(
        "import test from 'node:test';\n"
        "import assert from 'node:assert/strict';\n"
        "test('add note', () => assert.equal(1, 1));\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("# Notes CLI\n\n## Summary\n\nJavaScript notes CLI.\n", encoding="utf-8")

    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _controller(*, contract, cwd, **_kwargs):
        target = str(contract.allowed_targets[0])
        if target == "src/notes.js":
            diff = (
                "diff --git a/src/notes.js b/src/notes.js\n"
                "--- a/src/notes.js\n"
                "+++ b/src/notes.js\n"
                "@@ -1,3 +1,2 @@\n"
                "-export function addNote(notes, text) { return [...notes, text]; }\n"
                "-export function listNotes(notes) { return notes; }\n"
                "-export function completeNote(notes, index) { return notes; }\n"
                "+export function addNote(notes, text) { return [{ text }]; }\n"
                "+export function deleteNote(notes, index) { return notes.filter((_, i) => i !== index); }\n"
            )
        elif target == "tests/notes.test.js":
            diff = (
                "diff --git a/tests/notes.test.js b/tests/notes.test.js\n"
                "--- a/tests/notes.test.js\n"
                "+++ b/tests/notes.test.js\n"
                "@@ -1,3 +1,6 @@\n"
                "-import test from 'node:test';\n"
                "-import assert from 'node:assert/strict';\n"
                "-test('add note', () => assert.equal(1, 1));\n"
                "+const assert = require('assert');\n"
                "+describe('notes', () => {\n"
                "+  beforeEach(() => {});\n"
                "+  expect(1).toBe(1);\n"
                "+});\n"
            )
        else:
            diff = (
                "diff --git a/README.md b/README.md\n"
                "--- a/README.md\n"
                "+++ b/README.md\n"
                "@@ -1,4 +1,10 @@\n"
                "-# Notes CLI\n"
                "+# Notes Python CLI\n"
                " \n"
                " ## Summary\n"
                " \n"
                "-JavaScript notes CLI.\n"
                "+```python\n"
                "+def add_note(text):\n"
                "+    return text\n"
                "+```\n"
            )
        return {
            "attempted": True,
            "available": True,
            "status": "accepted",
            "failure_reason": None,
            "errors": [],
            "retry_attempted": False,
            "retry_count": 0,
            "result": types.SimpleNamespace(diff=diff, files=[target]),
            "provider_result": {},
        }

    monkeypatch.setattr("aegis_code.runtime.run_structured_proposal_controller", _controller)
    payload = build_run_payload(
        options=TaskOptions(
            task="add deleteNote(notes, index) with tests and README usage",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/notes.js", "tests/notes.test.js", "README.md"],
                "max_files": 3,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "destructive_public_api_rewrite"
    diagnostics = payload["patch_diff"].get("policy_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("policy_checked") is True
    assert int(diagnostics.get("policy_input_length", 0) or 0) > 200
    preview = str(diagnostics.get("policy_input_preview", "") or "")
    assert "diff --git a/src/notes.js b/src/notes.js" in preview
    assert diagnostics.get("detected_js_project") is True
    assert diagnostics.get("detected_node_test") is True
    assert diagnostics.get("detected_additive_task") is True
    assert diagnostics.get("detected_docs_language_mismatch") is True
    assert diagnostics.get("detected_readme_title_change") is True
    removed_symbols = diagnostics.get("detected_removed_public_symbols", [])
    assert "listNotes" in removed_symbols
    assert "completeNote" in removed_symbols
    assert diagnostics.get("final_policy_reason") == "destructive_public_api_rewrite"
    assert isinstance(diagnostics.get("policy_input_files"), list)
    assert "src/notes.js" in diagnostics.get("policy_input_files", [])
    assert "tests/notes.test.js" in diagnostics.get("policy_input_files", [])
    assert "README.md" in diagnostics.get("policy_input_files", [])
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()
    assert (tmp_path / ".aegis" / "runs" / "latest.invalid.diff").exists()


def test_generated_low_confidence_diff_includes_policy_diagnostics(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_main.py").write_text("def test_main():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _provider(**_kwargs):
        diff = (
            "diff --git a/app/main.py b/app/main.py\n"
            "--- a/app/main.py\n"
            "+++ b/app/main.py\n"
            "@@ -1,2 +1,5 @@\n"
            " def main():\n"
            "     return 1\n"
            "+\n"
            "+def delete_note(notes, index):\n"
            "+    return notes[:index] + notes[index+1:]\n"
        )
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": diff, "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    monkeypatch.setattr(
        "aegis_code.runtime.evaluate_diff",
        lambda *args, **kwargs: {
            "grounded": True,
            "relevant_files": True,
            "confidence": 0.35,
            "issues": [],
        },
    )

    payload = build_run_payload(
        options=TaskOptions(task="add delete_note helper", propose_patch=True),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert payload["patch_diff"]["status"] == "generated"
    diagnostics = payload["patch_diff"].get("policy_diagnostics")
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("policy_checked") is True
    assert diagnostics.get("final_policy_reason") is None


def test_real_node_unified_diff_policy_detectors_surface_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "notes.test.js").write_text(
        "import test from 'node:test';\nimport assert from 'node:assert/strict';\n",
        encoding="utf-8",
    )
    diff_text = (
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,8 +1,5 @@\n"
        "-export function addNote(notes, text) { return [...notes, text]; }\n"
        "-export function listNotes(notes) { return notes; }\n"
        "-export function completeNote(notes, index) { return notes; }\n"
        "+export function addNote(notes, text) { return notes.concat(text.toUpperCase()); }\n"
        "+export function deleteNote(notes, index) { return notes.filter((_, i) => i !== index); }\n"
        "diff --git a/tests/notes.test.js b/tests/notes.test.js\n"
        "--- a/tests/notes.test.js\n"
        "+++ b/tests/notes.test.js\n"
        "@@ -1,2 +1,6 @@\n"
        "+const assert = require('assert');\n"
        "+describe('notes', () => {\n"
        "+  beforeEach(() => {});\n"
        "+  expect(1).toBe(1);\n"
        "+});\n"
        "diff --git a/README.md b/README.md\n"
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1,5 +1,10 @@\n"
        "-# Node CLI Notes Validation\n"
        "+# Notes Application\n"
        " \n"
        " ## Summary\n"
        " \n"
        "+```python\n"
        "+def add_note(text):\n"
        "+    print(len(text))\n"
        "+    del notes[index]\n"
        "+```\n"
    )
    validation = {
        "valid": True,
        "files": [
            {"new_path": "src/notes.js", "old_path": "src/notes.js", "additions": 2, "deletions": 3},
            {"new_path": "tests/notes.test.js", "old_path": "tests/notes.test.js", "additions": 5, "deletions": 0},
            {"new_path": "README.md", "old_path": "README.md", "additions": 5, "deletions": 1},
        ],
        "summary": {"additions": 12, "deletions": 4},
    }
    diagnostics = hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation=validation,
        test_task=False,
        task_text="add deleteNote(notes, index) with tests and README usage",
        cwd=tmp_path,
    )
    assert diagnostics.get("policy_checked") is True
    assert diagnostics.get("detected_js_project") is True
    assert diagnostics.get("detected_node_test") is True
    assert diagnostics.get("detected_readme_title_change") is True
    assert diagnostics.get("detected_docs_language_mismatch") is True
    removed = diagnostics.get("detected_removed_public_symbols", [])
    assert "listNotes" in removed
    assert "completeNote" in removed
    assert diagnostics.get("final_policy_reason") in {
        "destructive_public_api_rewrite",
        "ecosystem_test_framework_mismatch",
        "docs_language_mismatch",
        "readme_title_changed",
    }


def test_add_delete_note_task_detects_removed_js_exports_as_destructive(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    diff_text = (
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,6 +1,5 @@\n"
        " export function addNote(notes, text) { return [...notes, text]; }\n"
        "-export function listNotes(notes) { return notes; }\n"
        "-export function completeNote(notes, index) { return notes; }\n"
        "+export function deleteNote(notes, index) { return notes.filter((_, i) => i !== index); }\n"
    )
    validation = {
        "valid": True,
        "files": [{"new_path": "src/notes.js", "old_path": "src/notes.js", "additions": 1, "deletions": 2}],
        "summary": {"additions": 1, "deletions": 2},
    }
    diagnostics = hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation=validation,
        test_task=False,
        task_text="add deleteNote(notes, index), tests and README usage",
        cwd=tmp_path,
    )
    removed = diagnostics.get("detected_removed_public_symbols", [])
    assert "listNotes" in removed
    assert "completeNote" in removed
    assert diagnostics.get("final_policy_reason") == "destructive_public_api_rewrite"


def test_explicit_remove_task_allows_js_export_removal(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module"}', encoding="utf-8")
    diff_text = (
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,2 @@\n"
        " export function addNote(notes, text) { return [...notes, text]; }\n"
        "-export function listNotes(notes) { return notes; }\n"
        " export function completeNote(notes, index) { return notes; }\n"
    )
    validation = {
        "valid": True,
        "files": [{"new_path": "src/notes.js", "old_path": "src/notes.js", "additions": 0, "deletions": 1}],
        "summary": {"additions": 0, "deletions": 1},
    }
    diagnostics = hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation=validation,
        test_task=False,
        task_text="remove listNotes",
        cwd=tmp_path,
    )
    assert diagnostics.get("final_policy_reason") is None


def test_js_exported_symbol_names_detects_removed_function_exports() -> None:
    symbols = _js_exported_symbol_names(
        [
            "export function listNotes(notes) {",
            "export function completeNote(notes, index) {",
        ]
    )
    assert symbols == {"listNotes", "completeNote"}


def test_policy_evaluator_minimal_js_removed_exports_diff_detected(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module"}', encoding="utf-8")
    diff_text = (
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,2 @@\n"
        "-export function listNotes(notes) {\n"
        "-export function completeNote(notes, index) {\n"
        "+export function deleteNote(notes, index) {\n"
    )
    diagnostics = hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation={
            "valid": True,
            "files": [{"new_path": "src/notes.js", "old_path": "src/notes.js", "additions": 1, "deletions": 2}],
            "summary": {"additions": 1, "deletions": 2},
        },
        test_task=False,
        task_text="add deleteNote(notes, index)",
        cwd=tmp_path,
    )
    removed = diagnostics.get("detected_removed_public_symbols", [])
    assert "listNotes" in removed
    assert "completeNote" in removed
    assert diagnostics.get("final_policy_reason") == "destructive_public_api_rewrite"


def test_is_additive_task_for_real_delete_note_addition_text() -> None:
    task = "add deleteNote(notes, index), tests for deleting a note, and README usage example"
    assert _is_additive_task(task) is True


def test_runtime_path_real_delete_note_task_sets_additive_and_detects_removed_exports(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "notes.test.js").write_text("import test from 'node:test';\n", encoding="utf-8")
    diff_text = (
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,6 +1,5 @@\n"
        " export function addNote(notes, text) { return [...notes, text]; }\n"
        "-export function listNotes(notes) { return notes; }\n"
        "-export function completeNote(notes, index) { return notes; }\n"
        "+export function deleteNote(notes, index) { return notes.filter((_, i) => i !== index); }\n"
    )
    diagnostics = hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation={
            "valid": True,
            "files": [{"new_path": "src/notes.js", "old_path": "src/notes.js", "additions": 1, "deletions": 2}],
            "summary": {"additions": 1, "deletions": 2},
        },
        test_task=False,
        task_text="add deleteNote(notes, index), tests for deleting a note, and README usage example",
        cwd=tmp_path,
    )
    assert diagnostics.get("detected_additive_task") is True
    removed = diagnostics.get("detected_removed_public_symbols", [])
    assert "listNotes" in removed
    assert "completeNote" in removed
    assert diagnostics.get("final_policy_reason") == "destructive_public_api_rewrite"


def test_additive_destructive_public_api_rewrite_triggers_one_corrective_regeneration(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"node-cli-notes","type":"module","scripts":{"test":"node --test"}}', encoding="utf-8")
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text(
        "export function addNote(notes, text) { return [...notes, text]; }\n"
        "export function listNotes(notes) { return notes; }\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": (
                    "diff --git a/src/notes.js b/src/notes.js\n"
                    "--- a/src/notes.js\n"
                    "+++ b/src/notes.js\n"
                    "@@ -1,2 +1,4 @@\n"
                    "-export function addNote(notes, text) { return [...notes, text]; }\n"
                    "-export function listNotes(notes) { return notes; }\n"
                    "+export function addNote(notes, text) { return [{ text }]; }\n"
                    "+export function hasNotes(notes) { return notes.length > 0; }\n"
                ),
                "error": None,
            }
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/notes.js b/src/notes.js\n"
                "--- a/src/notes.js\n"
                "+++ b/src/notes.js\n"
                "@@ -1,2 +1,6 @@\n"
                " export function addNote(notes, text) { return [...notes, text]; }\n"
                " export function listNotes(notes) { return notes; }\n"
                "+\n"
                "+export function hasNotes(notes) {\n"
                "+  return notes.length > 0;\n"
                "+}\n"
            ),
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(
            task="add hasNotes(notes)",
            propose_patch=True,
            command="patch",
            scope_contract={
                "source": "cli_explicit",
                "allowed_targets": ["src/notes.js"],
                "max_files": 1,
                "allow_new_files": False,
                "allowed_operations": ["replace"],
                "missing_targets": [],
                "block_reason": None,
            },
        ),
        cwd=tmp_path,
        client=_CapturingClient(),
    )
    assert calls["count"] == 2
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["error"] is None
    assert payload["patch_diff"]["regeneration_attempted"] is True
