from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aegis_code.aegis_client import AegisBackendClient, client_from_env
from aegis_code.budget import BudgetState
from aegis_code.config import load_config
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.context.failure_context import build_failure_context
from aegis_code.context.repo_scan import scan_repo
from aegis_code.execution_loop import should_retry_tests, synthesize_symptoms
from aegis_code.models import CommandResult
from aegis_code.patches.diff_evaluator import evaluate_diff
from aegis_code.patches.diff_writer import write_latest_diff
from aegis_code.parsers.pytest_parser import parse_pytest_output
from aegis_code.planning.patch_generator import generate_patch_plan
from aegis_code.providers import generate_patch_diff
from aegis_code.report import write_reports
from aegis_code.routing import normalize_tier, resolve_model_for_tier
from aegis_code.sll_adapter import analyze_failures_sll
from aegis_code.tools.tests import run_configured_tests


@dataclass(slots=True)
class TaskOptions:
    task: str
    budget: float | None = None
    mode: str | None = None
    dry_run: bool = False
    analyze_failures: bool = True
    propose_patch: bool = False
    session: str | None = None
    no_report: bool = False
    project_context: dict[str, Any] | None = None
    budget_state: dict[str, Any] | None = None
    runtime_policy: dict[str, Any] | None = None


def _is_tests_passed(status: str, exit_code: int | None) -> bool:
    return status == "ok" and exit_code == 0


def _patch_diff_default() -> dict[str, Any]:
    return {
        "attempted": False,
        "available": False,
        "provider": None,
        "model": None,
        "path": None,
        "error": None,
        "preview": "",
    }


def build_run_payload(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    config = load_config(cwd)
    capabilities = detect_capabilities(cwd or Path.cwd())
    mode = options.mode or config.mode
    budget = BudgetState(total=options.budget if options.budget is not None else config.budget_per_task)

    repo_summary = scan_repo(cwd)
    commands_run: list[dict[str, Any]] = []
    failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    initial_failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    final_failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    failure_context: dict[str, Any] = {"files": []}
    sll_analysis: dict[str, Any] = {"available": False}
    symptoms: list[str] = ["unstable_workflow"]
    test_attempts: list[dict[str, Any]] = []
    patch_plan: dict[str, Any] = {
        "strategy": "Failure analysis disabled.",
        "confidence": 0.0,
        "proposed_changes": [],
    }
    patch_diff: dict[str, Any] = _patch_diff_default()
    patch_quality: dict[str, Any] | None = None
    retry_policy: dict[str, Any] = {
        "max_retries": 0,
        "allow_escalation": False,
        "retry_attempted": False,
        "retry_count": 0,
        "stopped_reason": "not_evaluated",
    }
    verification: dict[str, Any] = {
        "available": bool(config.commands.test.strip()),
        "test_command": config.commands.test.strip() or None,
        "detected_stack": capabilities.get("detected_stack"),
        "confidence": capabilities.get("confidence", "low"),
        "reason": capabilities.get("reason", "no verification command configured"),
    }

    if options.dry_run:
        aegis_client = client or client_from_env(config.aegis.base_url)
        decision = aegis_client.step_scope(
            step_name="aegis_code_task",
            step_input={"task": options.task},
            symptoms=symptoms,
            severity="medium",
            metadata={
                "task": options.task,
                "budget_total": budget.total,
                "budget_remaining": budget.remaining,
                **({"session_id": options.session} if options.session else {}),
            },
        )
        retry_policy["stopped_reason"] = "dry_run"
        notes = [
            "Dry-run mode: no commands executed.",
            "v0.4 is planning/reporting only and does not edit files.",
        ]
        status = "dry_run_planned"
    else:
        test_command = config.commands.test.strip()
        decision = None
        if test_command:
            initial_result: CommandResult = run_configured_tests(test_command, cwd=cwd)
            commands_run.append(initial_result.to_dict())
            initial_failures = parse_pytest_output(initial_result.full_output)
            final_failures = initial_failures
            failure_context = build_failure_context(final_failures.get("failed_tests", []), cwd or Path.cwd())
            sll_analysis = analyze_failures_sll(initial_result.full_output)
            symptoms = synthesize_symptoms(
                initial_failures,
                sll_analysis,
                base_symptoms=["unstable_workflow"],
            )
            test_attempts.append(
                {
                    "attempt": 1,
                    "command": test_command,
                    "status": initial_result.status,
                    "exit_code": initial_result.exit_code,
                    "failures": initial_failures,
                }
            )

            aegis_client = client or client_from_env(config.aegis.base_url)
            decision = aegis_client.step_scope(
                step_name="aegis_code_task",
                step_input={"task": options.task},
                symptoms=symptoms,
                severity="medium",
                metadata={
                    "task": options.task,
                    "budget_total": budget.total,
                    "budget_remaining": budget.remaining,
                    "failure_count": initial_failures.get("failure_count", 0),
                    "command_status": initial_result.status,
                    "initial_test_exit_code": initial_result.exit_code,
                    "sll_available": bool(sll_analysis.get("available", False)),
                    **(
                        {"sll_regime": sll_analysis.get("regime", "unknown")}
                        if sll_analysis.get("available", False)
                        else {}
                    ),
                    **({"session_id": options.session} if options.session else {}),
                },
            )

            retry_policy = {
                "max_retries": int(decision.max_retries),
                "allow_escalation": bool(decision.allow_escalation),
                "retry_attempted": False,
                "retry_count": 0,
                "stopped_reason": "initial_passed" if _is_tests_passed(initial_result.status, initial_result.exit_code) else "retry_not_allowed",
            }

            if should_retry_tests(
                decision=decision,
                initial_status=initial_result.status,
                initial_exit_code=initial_result.exit_code,
            ):
                for retry_index in range(1, int(decision.max_retries) + 1):
                    retry_result = run_configured_tests(test_command, cwd=cwd)
                    commands_run.append(retry_result.to_dict())
                    retry_failures = parse_pytest_output(retry_result.full_output)
                    final_failures = retry_failures
                    failure_context = build_failure_context(
                        final_failures.get("failed_tests", []),
                        cwd or Path.cwd(),
                    )
                    sll_analysis = analyze_failures_sll(retry_result.full_output)
                    symptoms = synthesize_symptoms(
                        final_failures,
                        sll_analysis,
                        base_symptoms=["unstable_workflow"],
                    )
                    test_attempts.append(
                        {
                            "attempt": retry_index + 1,
                            "command": test_command,
                            "status": retry_result.status,
                            "exit_code": retry_result.exit_code,
                            "failures": retry_failures,
                        }
                    )
                    retry_policy["retry_attempted"] = True
                    retry_policy["retry_count"] = retry_index
                    if _is_tests_passed(retry_result.status, retry_result.exit_code):
                        retry_policy["stopped_reason"] = "passed_after_retry"
                        break
                else:
                    retry_policy["stopped_reason"] = "max_retries_exhausted"

            final_passed = _is_tests_passed(
                test_attempts[-1]["status"],
                test_attempts[-1]["exit_code"],
            )
            if isinstance(decision.execution, dict) and decision.execution.get("status") in {
                "unavailable",
                "error",
            }:
                status = "completed_with_aegis_unavailable"
            elif final_passed and retry_policy["retry_count"] > 0:
                status = "completed_tests_passed_after_retry"
            elif final_passed:
                status = "completed_tests_passed"
            elif retry_policy["retry_count"] > 0:
                status = "completed_tests_failed_after_retry"
            else:
                status = "completed_tests_failed"

            notes = [
                "Executed safe baseline actions only.",
                "v0.4 controlled loop runs test retries only; no file edits.",
            ]
        else:
            aegis_client = client or client_from_env(config.aegis.base_url)
            decision = aegis_client.step_scope(
                step_name="aegis_code_task",
                step_input={"task": options.task},
                symptoms=symptoms,
                severity="medium",
                metadata={
                    "task": options.task,
                    "budget_total": budget.total,
                    "budget_remaining": budget.remaining,
                    "failure_count": 0,
                    "command_status": "missing",
                    "initial_test_exit_code": None,
                    "sll_available": False,
                    **({"session_id": options.session} if options.session else {}),
                },
            )
            status = "completed_no_commands"
            notes = [
                "No configured test command found.",
                "No verification command was available, so no fix can be verified.",
            ]
            retry_policy["stopped_reason"] = "no_test_command"

    if decision is None:
        decision = client_from_env(config.aegis.base_url).step_scope(
            step_name="aegis_code_task",
            step_input={"task": options.task},
            symptoms=symptoms,
            severity="medium",
            metadata={"task": options.task},
        )

    selected_tier = normalize_tier(decision.model_tier)
    selected_model = resolve_model_for_tier(config, selected_tier)

    if options.analyze_failures:
        if final_failures.get("failure_count", 0) == 0 and retry_policy.get("retry_count", 0) > 0:
            patch_plan = {
                "strategy": "No patch required after retry success.",
                "confidence": 0.98,
                "proposed_changes": [],
            }
        elif status == "completed_no_commands":
            patch_plan = {
                "strategy": "No test command executed; no failure-aware patch plan generated.",
                "confidence": 0.0,
                "proposed_changes": [],
            }
        else:
            patch_plan = generate_patch_plan(
                options.task,
                final_failures.get("failed_tests", []),
                failure_context,
                asdict(decision),
                sll_analysis,
            )
    else:
        patch_plan = generate_patch_plan(
            options.task,
            final_failures.get("failed_tests", []),
            {"files": []},
            asdict(decision),
            {"available": False},
        )

    execution_budget = {}
    if isinstance(decision.execution, dict):
        execution_budget = decision.execution.get("budget", {}) or {}
    failures = final_failures

    should_attempt_provider_diff = bool(options.propose_patch or config.patches.generate_diff)
    provider_enabled = bool(config.providers.enabled or options.propose_patch)
    final_failure_count = int(final_failures.get("failure_count", 0) or 0)
    has_context_files = bool(failure_context.get("files", []))
    has_proposed_changes = bool(patch_plan.get("proposed_changes", []))

    if (
        should_attempt_provider_diff
        and provider_enabled
        and verification.get("available", False)
        and final_failure_count > 0
        and (has_context_files or has_proposed_changes)
    ):
        provider_result = generate_patch_diff(
            provider=config.providers.provider,
            model=selected_model,
            task=options.task,
            failures=final_failures,
            context=failure_context,
            patch_plan=patch_plan,
            aegis_execution=decision.execution if isinstance(decision.execution, dict) else {},
            api_key_env=config.providers.api_key_env,
            max_context_chars=int(config.patches.max_context_chars),
        )
        diff_text = str(provider_result.get("diff", "") or "").strip()
        path_value: str | None = None
        if provider_result.get("available", False) and diff_text:
            diff_path = write_latest_diff(diff_text, cwd=cwd)
            path_value = str(diff_path)
            patch_quality = evaluate_diff(diff_text, final_failures, failure_context)
        patch_diff = {
            "attempted": True,
            "available": bool(provider_result.get("available", False)) and bool(path_value),
            "provider": provider_result.get("provider"),
            "model": provider_result.get("model"),
            "path": path_value,
            "error": provider_result.get("error"),
            "preview": diff_text[:800],
        }
        if provider_result.get("available", False) and not path_value:
            patch_diff["available"] = False
            patch_diff["error"] = "Diff generation returned empty output."
    elif should_attempt_provider_diff and not provider_enabled:
        patch_diff = {
            "attempted": True,
            "available": False,
            "provider": config.providers.provider,
            "model": selected_model,
            "path": None,
            "error": "Provider usage is disabled in config.",
            "preview": "",
        }

    payload = {
        "task": options.task,
        "mode": mode,
        "dry_run": options.dry_run,
        "budget": budget.to_dict(),
        "aegis_execution": decision.execution,
        "aegis_decision": asdict(decision),
        "selected_model_tier": selected_tier,
        "selected_model": selected_model,
        "repo_scan": repo_summary.to_dict(),
        "commands_run": commands_run,
        "test_attempts": test_attempts,
        "initial_failures": initial_failures,
        "final_failures": final_failures,
        "symptoms": symptoms,
        "retry_policy": retry_policy,
        "failures": failures,
        "failure_context": failure_context,
        "sll_analysis": sll_analysis,
        "patch_plan": patch_plan,
        "patch_diff": patch_diff,
        "patch_quality": patch_quality,
        "verification": verification,
        "status": status,
        "notes": notes,
        "execution_budget_pressure": execution_budget,
        "project_context": {
            "available": bool((options.project_context or {}).get("available", False)),
            "included_paths": list((options.project_context or {}).get("included_paths", [])),
            "total_chars": int((options.project_context or {}).get("total_chars", 0) or 0),
        },
        "budget_state": {
            "available": bool((options.budget_state or {}).get("available", False)),
            "limit": (options.budget_state or {}).get("limit"),
            "spent_estimate": (options.budget_state or {}).get("spent_estimate"),
            "remaining_estimate": (options.budget_state or {}).get("remaining_estimate"),
        },
        "runtime_policy": {
            "requested_mode": (options.runtime_policy or {}).get("requested_mode"),
            "selected_mode": (options.runtime_policy or {}).get("selected_mode"),
            "reason": (options.runtime_policy or {}).get("reason"),
            "budget_present": bool((options.runtime_policy or {}).get("budget_present", False)),
            "context_available": bool((options.runtime_policy or {}).get("context_available", False)),
        },
    }
    return payload


def _run_task_local(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    payload = build_run_payload(options=options, cwd=cwd, client=client)
    if write_report and not options.no_report:
        write_reports(payload, cwd=cwd)
    return payload


def run_task(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    from aegis_code.runtime_adapter import execute_task

    return execute_task(task_options=options, cwd=cwd, client=client)
