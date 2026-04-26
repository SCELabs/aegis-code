from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from aegis_code.aegis_client import AegisBackendClient, client_from_env
from aegis_code.budget import BudgetState
from aegis_code.config import load_config
from aegis_code.context.repo_scan import scan_repo
from aegis_code.models import CommandResult
from aegis_code.report import write_reports
from aegis_code.routing import normalize_tier, resolve_model_for_tier
from aegis_code.tools.tests import run_configured_tests


@dataclass(slots=True)
class TaskOptions:
    task: str
    budget: float | None = None
    mode: str | None = None
    dry_run: bool = False
    session: str | None = None
    no_report: bool = False


def build_run_payload(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    config = load_config(cwd)
    mode = options.mode or config.mode
    budget = BudgetState(total=options.budget if options.budget is not None else config.budget_per_task)

    aegis_client = client or client_from_env(config.aegis.base_url)
    decision = aegis_client.step_scope(
        step_name="aegis_code_task",
        step_input={"task": options.task},
        symptoms=["unstable_workflow"],
        severity="medium",
        metadata={
            "budget_total": budget.total,
            "budget_remaining": budget.remaining,
            **({"session_id": options.session} if options.session else {}),
        },
    )

    selected_tier = normalize_tier(decision.model_tier)
    selected_model = resolve_model_for_tier(config, selected_tier)

    repo_summary = scan_repo(cwd)
    commands_run: list[dict[str, Any]] = []

    if options.dry_run:
        notes = [
            "Dry-run mode: no commands executed.",
            "v0.1 is planning/reporting only and does not edit files.",
        ]
        status = "dry_run_planned"
    else:
        test_command = config.commands.test.strip()
        if test_command:
            cmd_result: CommandResult = run_configured_tests(test_command, cwd=cwd)
            commands_run.append(cmd_result.to_dict())
            status = "completed_with_safe_actions"
            notes = [
                "Executed safe baseline actions only.",
                "v0.1 does not edit files.",
            ]
        else:
            status = "completed_no_commands"
            notes = [
                "No configured test command found.",
                "v0.1 is planning/reporting only and does not edit files.",
            ]

    execution_budget = {}
    if isinstance(decision.execution, dict):
        execution_budget = decision.execution.get("budget", {}) or {}

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
        "status": status,
        "notes": notes,
        "execution_budget_pressure": execution_budget,
    }
    return payload


def run_task(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    payload = build_run_payload(options=options, cwd=cwd, client=client)
    if not options.no_report:
        write_reports(payload, cwd=cwd)
    return payload
