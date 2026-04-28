from __future__ import annotations

from pathlib import Path

from aegis_code.models import AegisDecision, CommandResult
from aegis_code.runtime import TaskOptions, build_run_payload, run_task
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
    assert payload["status"] == "completed_with_aegis_unavailable"
    assert len(payload["test_attempts"]) == 1
    assert (tmp_path / ".aegis" / "runs" / "latest.md").exists()
