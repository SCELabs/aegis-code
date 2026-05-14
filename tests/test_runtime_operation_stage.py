from __future__ import annotations

from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.operations import OperationResult, normalize_operation_contract
from aegis_code.runtime import TaskOptions, build_run_payload
from aegis_code.runtime_components.operation_stage import run_operation_stage
from tests.helpers import command_result_from_output, pytest_output_fail


class _Client:
    def step_scope(self, **_kwargs: object) -> AegisDecision:
        return AegisDecision(
            model_tier="mid",
            context_mode="focused",
            max_retries=0,
            allow_escalation=False,
            execution={"budget": {"pressure": "low"}},
        )


def test_run_operation_stage_builds_request_and_returns_result(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run_operation(request):
        captured["request"] = request
        return OperationResult(
            attempted=True,
            status="generated",
            diff_text="diff --git a/tests/test_cli.py b/tests/test_cli.py\n",
            operation=request.contract.operation,
            source=request.contract.source,
        )

    monkeypatch.setattr("aegis_code.runtime_components.operation_stage.run_operation", _fake_run_operation)
    contract = normalize_operation_contract(
        operation="append",
        target_file="tests/test_cli.py",
        source="cli",
    )
    result = run_operation_stage(
        contract=contract,
        task="append tests",
        cwd=tmp_path,
        context={"provider": "openai"},
        failures={"failure_count": 1},
        patch_plan={"allowed_targets": ["tests/test_cli.py"]},
        aegis_execution={"available": True},
        model="gpt-4.1-mini",
        provider_timeout=30,
    )

    assert result.status == "generated"
    request = captured.get("request")
    assert request is not None
    assert request.contract.operation == "append"
    assert request.task == "append tests"
    assert request.cwd == tmp_path
    assert request.context == {"provider": "openai"}
    assert request.failures == {"failure_count": 1}
    assert request.patch_plan == {"allowed_targets": ["tests/test_cli.py"]}
    assert request.aegis_execution == {"available": True}
    assert request.model == "gpt-4.1-mini"
    assert request.provider_timeout == 30


def test_run_operation_stage_unsupported_operation_returns_blocked(tmp_path: Path) -> None:
    contract = normalize_operation_contract(
        operation="replace",
        target_file="src/main.py",
        source="cli",
    )
    result = run_operation_stage(
        contract=contract,
        task="replace logic",
        cwd=tmp_path,
        context={},
        failures={},
        patch_plan={},
        aegis_execution={},
        model="gpt-4.1-mini",
    )
    assert result.attempted is False
    assert result.status == "blocked"
    assert result.error == "operation_contract_invalid"
    assert result.operation == "replace"
    assert result.source == "cli"


def test_runtime_operation_flow_preserves_patch_operation_metadata(monkeypatch, tmp_path: Path) -> None:
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
        "aegis_code.runtime.generate_structured_edits",
        lambda **_: (_ for _ in ()).throw(AssertionError("structured edits should not run for create-file")),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: (_ for _ in ()).throw(AssertionError("fallback should not run for create-file")),
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
        client=_Client(),
    )
    assert payload["patch_operation"]["operation"] == "create-file"
    assert payload["patch_operation"]["source"] == "cli"
