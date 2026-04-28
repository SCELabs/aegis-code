from __future__ import annotations

from typing import Any

from aegis_code.models import AegisDecision


def synthesize_symptoms(
    failures: dict[str, Any],
    sll_analysis: dict[str, Any] | None,
    base_symptoms: list[str] | None = None,
) -> list[str]:
    symptoms: list[str] = list(base_symptoms or [])
    failure_count = int(failures.get("failure_count", 0) or 0)
    failed_tests = failures.get("failed_tests", []) or []

    if failure_count > 0:
        symptoms.append("test_failure")
    if any(not str(item.get("file", "")).strip() for item in failed_tests if isinstance(item, dict)):
        symptoms.append("incomplete_failure_signal")

    sll = sll_analysis or {}
    if sll.get("available", False):
        if float(sll.get("fragmentation_risk", 0.0)) > 0.6:
            symptoms.append("fragmented_output")
        if float(sll.get("collapse_risk", 0.0)) > 0.6:
            symptoms.append("degenerate_loop")
        if float(sll.get("drift_risk", 0.0)) > 0.6:
            symptoms.append("unstable_workflow")
        if float(sll.get("stable_random_risk", 0.0)) > 0.6:
            symptoms.append("ungrounded_output")

    deduped: list[str] = []
    for symptom in symptoms:
        if symptom not in deduped:
            deduped.append(symptom)
    return deduped


def execution_guidance_allows_retry(execution: dict[str, Any]) -> bool:
    if not isinstance(execution, dict):
        return False
    for key in ("retry", "allow_retry", "stabilize", "stabilization"):
        value = execution.get(key)
        if isinstance(value, bool) and value:
            return True
    policy = execution.get("policy")
    if isinstance(policy, dict):
        action = str(policy.get("action", "")).lower()
        if action in {"retry", "stabilize", "stabilization"}:
            return True
    mode = str(execution.get("mode", "")).lower()
    return mode in {"retry", "stabilize", "stabilization"}


def should_retry_tests(
    *,
    decision: AegisDecision,
    initial_status: str,
    initial_exit_code: int | None,
) -> bool:
    if initial_status == "ok" and initial_exit_code == 0:
        return False
    if int(decision.max_retries) <= 0:
        return False
    if decision.allow_escalation:
        return True
    return execution_guidance_allows_retry(decision.execution if isinstance(decision.execution, dict) else {})

