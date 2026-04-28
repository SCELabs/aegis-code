from __future__ import annotations

from pathlib import Path

from aegis_code.models import AegisDecision, CommandResult
from aegis_code.runtime import TaskOptions, build_run_payload


class _CapturingClient:
    def __init__(self) -> None:
        self.last_symptoms: list[str] = []

    def step_scope(self, **kwargs: object) -> AegisDecision:
        symptoms = kwargs.get("symptoms", [])
        if isinstance(symptoms, list):
            self.last_symptoms = [str(item) for item in symptoms]
        return AegisDecision(
            model_tier="mid",
            context_mode="focused",
            execution={"budget": {"pressure": "low"}},
        )


def test_runtime_maps_sll_risks_into_symptoms(monkeypatch, tmp_path: Path) -> None:
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
            full_output="FAILED tests/test_x.py::test_x - AssertionError",
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
    assert "fragmented_output" in client.last_symptoms
    assert "degenerate_loop" in client.last_symptoms
    assert "unstable_workflow" in client.last_symptoms
    assert "ungrounded_output" in client.last_symptoms

