from __future__ import annotations

import json
from pathlib import Path

from aegis_code.models import AegisDecision, CommandResult
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
