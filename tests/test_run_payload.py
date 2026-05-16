from __future__ import annotations

from aegis_code.run_payload import build_run_payload_base, normalize_run_payload


def test_build_run_payload_base_sets_schema_version_default() -> None:
    payload = build_run_payload_base(task="x")
    assert payload["schema_version"] == 1


def test_build_run_payload_base_merges_extra_fields() -> None:
    payload = build_run_payload_base(task="x", status="ok", retry_policy={"retry_count": 0})
    assert payload["task"] == "x"
    assert payload["status"] == "ok"
    assert payload["retry_policy"]["retry_count"] == 0


def test_guidance_compat_prefers_advisory_then_control() -> None:
    advisory = {"available": True, "explanation": "advisory"}
    control = {"model_tier": "cheap"}
    payload = build_run_payload_base(
        task="x",
        control_guidance=control,
        advisory_guidance=advisory,
    )
    assert payload["control_guidance"] == control
    assert payload["advisory_guidance"] == advisory
    assert payload["aegis_guidance"] == advisory

    control_only = build_run_payload_base(task="x", control_guidance=control)
    assert control_only["aegis_guidance"] == control


def test_normalize_run_payload_handles_partial_payload() -> None:
    payload = normalize_run_payload(
        {
            "task": "x",
            "mode": "balanced",
            "selected_model": "openai:gpt-4.1-mini",
            "selected_model_tier": "mid",
            "provider_timeout_seconds": 60,
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        }
    )
    assert payload["schema_version"] == 1
    assert payload["control_guidance"] is None
    assert payload["advisory_guidance"] is None
    assert payload["aegis_guidance"] is None
    assert payload["model_selection"]["provider"] == "openai"
    assert payload["model_selection"]["model"] == "gpt-4.1-mini"
    assert payload["model_selection"]["tier"] == "mid"
    assert payload["model_selection"]["provider_timeout_seconds"] == 60

