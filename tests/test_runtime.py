from __future__ import annotations

from pathlib import Path

from aegis_code.models import AegisDecision, CommandResult
from aegis_code.runtime import TaskOptions, build_run_payload


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
        lambda _cmd, cwd=None: CommandResult(
            name="test",
            command="pytest -q",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="boom",
            output_preview="boom",
            full_output="FAILED tests/test_x.py::test_x - AssertionError: boom",
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


def test_retry_loop_success_after_retry(monkeypatch, tmp_path: Path) -> None:
    results = [
        CommandResult(
            name="test",
            command="pytest -q",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="boom",
            output_preview="boom",
            full_output="FAILED tests/test_x.py::test_x - AssertionError: boom",
        ),
        CommandResult(
            name="test",
            command="pytest -q",
            status="ok",
            exit_code=0,
            stdout="ok",
            stderr="",
            output_preview="ok",
            full_output="1 passed in 0.01s",
        ),
    ]

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


def test_retry_loop_no_retry_without_permission(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: CommandResult(
            name="test",
            command="pytest -q",
            status="failed",
            exit_code=1,
            stdout="",
            stderr="boom",
            output_preview="boom",
            full_output="FAILED tests/test_x.py::test_x - AssertionError: boom",
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
