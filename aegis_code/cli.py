from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from aegis_code.budget import can_spend, clear_budget, get_budget_state, load_budget, record_event, set_budget
from aegis_code.config import load_config
from aegis_code.compare import build_comparison, format_comparison, load_last_runs
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.context_state import (
    format_context_refresh,
    format_context_show,
    load_runtime_context,
    refresh_context,
    show_context,
)
from aegis_code.create_plan import build_create_plan, format_create_plan
from aegis_code.create_scaffold import create_scaffold
from aegis_code.maintain import build_maintenance_report, format_maintenance_report
from aegis_code.next_actions import build_next_actions, format_next_actions
from aegis_code.onboard import run_onboard
from aegis_code.overview import build_overview, format_overview
from aegis_code.provider_presets import PRESETS, apply_preset, detect_available_providers
from aegis_code.patches.apply_check import check_patch_file, format_apply_check_result
from aegis_code.patches.backups import list_backups, restore_backup
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.patch_applier import apply_patch_file, format_apply_result
from aegis_code.policy import (
    build_runtime_policy_payload,
    build_policy_status,
    format_runtime_control_summary,
    format_policy_status,
    get_mode_reason,
    select_runtime_mode,
)
from aegis_code.config import ensure_project_files, project_paths, update_model_tier
from aegis_code.report import read_latest_markdown, write_reports
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.scaffolds import list_stacks
from aegis_code.secrets import (
    clear_key,
    get_status as get_secrets_status,
    list_scoped_keys,
    mask_key,
    resolve_key_source,
    set_key,
)
from aegis_code.setup import check_setup, run_setup
from aegis_code.sll_adapter import check_sll_available
from aegis_code.tools.tests import run_configured_tests
from aegis_code.usage import get_usage_warning, load_usage
from aegis_code.workspace import (
    add_project,
    compare_workspace_runs,
    get_detailed_status,
    get_status,
    get_workspace_overview,
    init_workspace,
    preview_workspace_run,
    refresh_workspace_context,
    remove_project,
    run_workspace_task,
)


def _format_adapter_summary(adapter: dict[str, object] | None) -> str:
    info = adapter or {}
    status = str(info.get("control_status", "disabled"))
    reason = str(info.get("control_reason", info.get("fallback_reason", "n/a")))
    lines = [
        "Aegis Control:",
        f"- Status: {status}",
        f"- Reason: {reason}",
        f"- Client available: {'true' if bool(info.get('aegis_client_available', False)) else 'false'}",
        f"- Execution: {info.get('execution', 'local')}",
        f"- Mutation: {'confirm-only' if str(info.get('mutation', 'confirm_only')) == 'confirm_only' else info.get('mutation')}",
    ]
    if info.get("error_type"):
        lines.append(f"- Error type: {info.get('error_type')}")
    if info.get("error_message"):
        lines.append(f"- Error: {info.get('error_message')}")
    return "\n".join(lines)


def _format_aegis_impact(impact: dict[str, object] | None) -> str:
    info = impact or {}
    lines = [
        "Aegis Impact:",
        f"- Guidance used: {'true' if bool(info.get('used', False)) else 'false'}",
        f"- Actions returned: {int(info.get('action_count', 0) or 0)}",
        f"- Override applied: {'true' if bool(info.get('override_applied', False)) else 'false'}",
        f"- Fallback used: {'true' if bool(info.get('fallback_used', False)) else 'false'}",
    ]
    if info.get("reason"):
        lines.append(f"- Reason: {info.get('reason')}")
    return "\n".join(lines)


def _print_aegis_impact_if_relevant(payload: dict[str, object]) -> None:
    adapter = payload.get("adapter")
    impact = payload.get("aegis_impact")
    adapter_info = adapter if isinstance(adapter, dict) else {}
    impact_info = impact if isinstance(impact, dict) else {}
    available = bool(adapter_info.get("aegis_client_available", False))
    used = bool(impact_info.get("used", False))
    if available or used:
        print(_format_aegis_impact(impact_info))


def _format_aegis_usage(usage: dict[str, object] | None) -> str:
    info = usage or {}
    lines = [
        "Aegis Usage:",
        f"- Attempts: {int(info.get('calls', 0) or 0)}",
        f"- Successful: {int(info.get('successful', 0) or 0)}",
        f"- Fallbacks: {int(info.get('fallbacks', 0) or 0)}",
        f"- Actions applied: {int(info.get('actions_applied', 0) or 0)}",
    ]
    return "\n".join(lines)


def _print_aegis_usage_if_available(payload: dict[str, object], cwd: Path) -> None:
    adapter = payload.get("adapter")
    adapter_info = adapter if isinstance(adapter, dict) else {}
    if bool(adapter_info.get("aegis_client_available", False)):
        usage = load_usage(cwd)
        print(_format_aegis_usage(usage))
        warning = get_usage_warning(usage)
        if warning:
            limit = int(warning.get("limit", 100) or 100)
            if warning.get("type") == "approaching_limit":
                print(f"⚠ Approaching Aegis usage limit ({limit} calls)")
            elif warning.get("type") == "limit_reached":
                print(f"⚠ Aegis usage limit reached ({limit} calls)")
                print("Aegis will continue to run, but limits may apply in future versions.")


def _build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code init")
    parser.add_argument("--force", action="store_true", help="Overwrite default project files.")
    return parser


def _build_report_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code report")


def _build_status_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code status")


def _build_compare_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code compare")


def _build_overview_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code overview")


def _build_maintain_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code maintain")


def _build_create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code create")
    parser.add_argument("idea", nargs="?", default=None, help="Project idea to plan.")
    parser.add_argument("--list-stacks", action="store_true", help="List available stack profiles and exit.")
    parser.add_argument("--stack", default=None, help="Optional stack profile id override.")
    parser.add_argument("--target", default=None, help="Optional scaffold target directory (requires --confirm).")
    parser.add_argument("--confirm", action="store_true", help="Confirm writing scaffold files to --target.")
    parser.add_argument("--validate", action="store_true", help="Run validation after confirmed scaffold.")
    return parser


def _build_doctor_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code doctor")


def _build_onboard_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code onboard")
    parser.add_argument("--email", required=False)
    return parser


def _build_context_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code context")
    subparsers = parser.add_subparsers(dest="context_command")
    subparsers.add_parser("refresh", prog="aegis-code context refresh")
    subparsers.add_parser("show", prog="aegis-code context show")
    return parser


def _build_budget_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code budget")
    subparsers = parser.add_subparsers(dest="budget_command")
    set_parser = subparsers.add_parser("set", prog="aegis-code budget set")
    set_parser.add_argument("amount", type=float, help="Budget limit estimate in USD.")
    subparsers.add_parser("status", prog="aegis-code budget status")
    subparsers.add_parser("clear", prog="aegis-code budget clear")
    return parser


def _build_policy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code policy")
    subparsers = parser.add_subparsers(dest="policy_command")
    subparsers.add_parser("status", prog="aegis-code policy status")
    return parser


def _build_provider_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code provider")
    subparsers = parser.add_subparsers(dest="provider_command")
    subparsers.add_parser("status", prog="aegis-code provider status")
    model_parser = subparsers.add_parser("model", prog="aegis-code provider model")
    model_parser.add_argument("tier")
    model_parser.add_argument("value")
    subparsers.add_parser("list", prog="aegis-code provider list")
    subparsers.add_parser("detect", prog="aegis-code provider detect")
    preset_parser = subparsers.add_parser("preset", prog="aegis-code provider preset")
    preset_parser.add_argument("name")
    return parser


def _build_keys_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code keys")
    subparsers = parser.add_subparsers(dest="keys_command")

    set_parser = subparsers.add_parser("set")
    set_parser.add_argument("name")
    set_parser.add_argument("value", nargs="?", default=None)
    set_parser.add_argument("--global", dest="global_scope", action="store_true")
    set_parser.add_argument("--project", dest="project_scope", action="store_true")
    set_parser.add_argument("--yes", action="store_true")

    clear_parser = subparsers.add_parser("clear")
    clear_parser.add_argument("name")
    clear_parser.add_argument("--global", dest="global_scope", action="store_true")
    clear_parser.add_argument("--project", dest="project_scope", action="store_true")

    subparsers.add_parser("status")
    subparsers.add_parser("list")
    return parser


def _build_workspace_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code workspace")
    subparsers = parser.add_subparsers(dest="workspace_command")
    subparsers.add_parser("init", prog="aegis-code workspace init")
    add_parser = subparsers.add_parser("add", prog="aegis-code workspace add")
    add_parser.add_argument("path")
    remove_parser = subparsers.add_parser("remove", prog="aegis-code workspace remove")
    remove_parser.add_argument("path")
    status_parser = subparsers.add_parser("status", prog="aegis-code workspace status")
    status_parser.add_argument("--detailed", action="store_true")
    subparsers.add_parser("overview", prog="aegis-code workspace overview")
    subparsers.add_parser("compare", prog="aegis-code workspace compare")
    subparsers.add_parser("refresh-context", prog="aegis-code workspace refresh-context")
    run_parser = subparsers.add_parser("run", prog="aegis-code workspace run")
    run_parser.add_argument("task")
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--confirm", action="store_true")
    return parser


def _build_backups_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code backups")


def _build_restore_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code restore")
    parser.add_argument("backup_id", help="Backup snapshot id under .aegis/backups.")
    return parser


def _build_apply_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code apply")
    parser.add_argument("path", nargs="?", default=None, help="Patch diff path.")
    parser.add_argument("--check", metavar="PATH", default=None, help="Validate diff file without applying.")
    parser.add_argument("--confirm", action="store_true", help="Confirm patch apply (human-approved).")
    return parser


def _build_check_sll_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code --check-sll")


def _build_fix_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code fix")
    parser.add_argument("--confirm", action="store_true", help="Confirm apply for proposed patch.")
    return parser


def _build_next_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code next")


def _build_usage_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code usage")


def _build_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code setup")
    parser.add_argument("--email", default=None)
    parser.add_argument("--skip-aegis", action="store_true")
    parser.add_argument("--skip-provider", action="store_true")
    parser.add_argument("--skip-first-run", action="store_true")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def _build_task_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code")
    parser.add_argument("task", help="Task prompt for Aegis guidance.")
    parser.add_argument("--budget", type=float, default=None, help="Budget cap for this task.")
    parser.add_argument(
        "--mode",
        choices=["cheapest", "balanced", "premium-fallback", "local-first"],
        default=None,
        help="Runtime mode hint.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; skip commands.")
    parser.add_argument(
        "--analyze-failures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable failure-aware parsing/context/planning (default: enabled).",
    )
    parser.add_argument(
        "--propose-patch",
        action="store_true",
        help="Attempt provider-backed diff proposal (proposal-only).",
    )
    parser.add_argument("--session", default=None, help="Optional session id/name.")
    parser.add_argument("--no-report", action="store_true", help="Skip writing latest report files.")
    parser.add_argument("--quiet", action="store_true", help="Suppress progress updates.")
    return parser


def handle_init(argv: Sequence[str]) -> int:
    parser = _build_init_parser()
    args = parser.parse_args(list(argv))
    cfg_path = project_paths()["config_path"]
    detected = detect_capabilities(Path.cwd())
    detected_test_command = (
        str(detected.get("test_command", "") or "")
        if bool(detected.get("verification_available", False))
        else ""
    )
    should_write_config = args.force or not cfg_path.exists()
    created = ensure_project_files(force=args.force, test_command=detected_test_command if should_write_config else None)
    paths = project_paths()
    print(f"Initialized: {paths['aegis_dir']}")
    print(f"Config: {paths['config_path']} ({'created' if created['config_created'] else 'kept'})")
    print(
        "Project model: "
        f"{paths['project_model_path']} ({'created' if created['project_model_created'] else 'kept'})"
    )
    if should_write_config:
        if detected_test_command:
            print(f"Detected test command: {detected_test_command}")
        else:
            print("Detected no verification command. commands.test left empty.")
    print("No autonomous file editing is performed.")
    return 0


def handle_report(argv: Sequence[str]) -> int:
    parser = _build_report_parser()
    parser.parse_args(list(argv))
    latest = read_latest_markdown()
    if not latest:
        print("No report found at .aegis/runs/latest.md. Run a task first.")
        return 1
    path, content = latest
    print(f"Latest report: {path}")
    print("")
    print(content)
    return 0


def handle_status(argv: Sequence[str]) -> int:
    parser = _build_status_parser()
    parser.parse_args(list(argv))
    paths = project_paths()
    latest = paths["latest_json"]
    if not latest.exists():
        print('No latest run found. Run aegis-code "<task>" first.')
        return 1
    payload = json.loads(latest.read_text(encoding="utf-8"))
    backups = list_backups(cwd=Path.cwd()).get("backups", [])
    sll = payload.get("sll_analysis", {}) or {}
    patch_diff = payload.get("patch_diff", {}) or {}
    patch_quality = payload.get("patch_quality")
    verification = payload.get("verification", {}) or {}
    detected = detect_capabilities(Path.cwd())
    ver_available = verification.get("available")
    ver_command = verification.get("test_command")
    ver_stack = verification.get("detected_stack")
    has_verification = (
        isinstance(verification, dict)
        and ver_available is not None
        and bool(str(ver_command or "").strip())
        and bool(str(ver_stack or "").strip())
    )
    if not has_verification:
        verification = {
            "available": bool(detected.get("verification_available", False)),
            "test_command": detected.get("test_command"),
            "detected_stack": detected.get("detected_stack"),
        }

    print("Status:")
    print(f"- Task: {payload.get('task', '')}")
    print(f"- Run status: {payload.get('status', '')}")
    print(f"- Failure count: {payload.get('failures', {}).get('failure_count', 0)}")
    print(
        f"- Verification: available={verification.get('available', False)} command={verification.get('test_command') or 'n/a'} stack={verification.get('detected_stack') or 'n/a'}"
    )
    print(
        f"- SLL: available={sll.get('available', False)} regime={sll.get('regime', 'n/a') if sll.get('available', False) else 'n/a'}"
    )
    print(
        f"- Patch diff: attempted={patch_diff.get('attempted', False)} available={patch_diff.get('available', False)} path={patch_diff.get('path', 'n/a')}"
    )
    if patch_quality:
        print(f"- Patch quality confidence: {patch_quality.get('confidence', 0.0)}")
    else:
        print("- Patch quality confidence: n/a")
    print(f"- Backup count: {len(backups)}")
    return 0


def handle_compare(argv: Sequence[str]) -> int:
    parser = _build_compare_parser()
    parser.parse_args(list(argv))
    prev, current = load_last_runs(cwd=Path.cwd())
    if current is None:
        print("No runs found. Run aegis-code \"<task>\" first.")
        return 1
    if prev is None:
        print("Only one run found. Need at least two runs to compare.")
        return 1
    data = build_comparison(prev, current)
    print(format_comparison(data))
    return 0


def handle_overview(argv: Sequence[str]) -> int:
    parser = _build_overview_parser()
    parser.parse_args(list(argv))
    data = build_overview(cwd=Path.cwd())
    print(format_overview(data))
    return 0


def handle_maintain(argv: Sequence[str]) -> int:
    parser = _build_maintain_parser()
    parser.parse_args(list(argv))
    report = build_maintenance_report(cwd=Path.cwd())
    print(format_maintenance_report(report))
    return 0


def handle_create(argv: Sequence[str]) -> int:
    parser = _build_create_parser()
    args = parser.parse_args(list(argv))
    if args.list_stacks:
        print("Available stacks:")
        for profile in list_stacks():
            print(f"- {profile.get('id', 'unknown')}@{profile.get('version', 'unknown')}")
        return 0
    if not args.idea:
        parser.print_usage()
        print("error: the following arguments are required: idea")
        return 2
    if args.validate and (not args.confirm or not args.target):
        print("Validation requires --confirm (scaffold must exist).")
        return 2
    try:
        plan = build_create_plan(args.idea, cwd=Path.cwd(), stack_id=args.stack)
    except ValueError as exc:
        print(str(exc))
        return 2
    print(format_create_plan(plan))
    if not args.target:
        return 0

    result = create_scaffold(
        target=Path(args.target),
        cwd=Path.cwd(),
        stack_id=str(plan.get("stack", {}).get("name", "python-basic")),
        stack_version=str(plan.get("stack", {}).get("version", "0.1")),
        idea=str(plan.get("idea", "")),
        test_command=str(plan.get("test_command", "python -m pytest -q")),
        confirm=bool(args.confirm),
    )
    print("")
    print(f"Scaffold target: {result.get('target', args.target)}")
    print(result.get("message", ""))
    files = result.get("files", []) or result.get("written", [])
    if files:
        print("Files:")
        for item in files:
            print(f"- {item}")
    print(f"Applied: {'true' if result.get('applied', False) else 'false'}")
    exit_code = int(result.get("code", 2))
    if exit_code != 0 or not args.validate:
        return exit_code

    target_path = Path(args.target)
    validation = run_configured_tests(str(plan.get("test_command", "") or "").strip(), cwd=target_path)
    if validation.status == "ok" and validation.exit_code == 0:
        print("Validation: tests passed.")
        return 0

    print("Validation: tests failed. Running Aegis stabilization...")
    cfg = load_config(target_path)
    base_mode = cfg.mode
    final_mode = select_runtime_mode(base_mode, cwd=target_path)
    reason = get_mode_reason(base_mode, final_mode, cwd=target_path)
    if not _allow_runtime_or_print(target_path, selected_mode=final_mode, reason=reason):
        return 0
    project_context = load_runtime_context(cwd=target_path)
    budget_state = get_budget_state(cwd=target_path)
    runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=target_path)
    payload = run_task(
        options=TaskOptions(
            task="fix failing tests after scaffold",
            mode=final_mode,
            propose_patch=True,
            project_context=project_context,
            budget_state=budget_state,
            runtime_policy=runtime_policy,
        ),
        cwd=target_path,
    )
    print(format_runtime_control_summary(runtime_policy, budget_state, project_context))
    print(_format_adapter_summary(payload.get("adapter")))
    _print_aegis_impact_if_relevant(payload)
    _print_aegis_usage_if_available(payload, target_path)
    print("Aegis stabilization plan generated.")
    print("Report JSON: .aegis/runs/latest.json")
    print("Report MD: .aegis/runs/latest.md")
    return 0


def handle_doctor(argv: Sequence[str]) -> int:
    parser = _build_doctor_parser()
    parser.parse_args(list(argv))
    cwd = Path.cwd()
    cfg = load_config(cwd)
    caps = detect_capabilities(cwd)
    sll = check_sll_available()
    paths = project_paths(cwd)
    latest = paths["latest_json"]
    backups = list_backups(cwd=cwd).get("backups", [])

    aegis_key_configured = bool(os.environ.get("AEGIS_API_KEY", "").strip())
    provider_env = str(cfg.providers.api_key_env or "OPENAI_API_KEY")
    provider_key_configured = bool(os.environ.get(provider_env, "").strip())
    if not cfg.providers.enabled:
        provider_state = "disabled"
    elif provider_key_configured:
        provider_state = "configured"
    else:
        provider_state = "missing"

    print("Aegis Code Doctor")
    print("")
    print("Repo:")
    print(f"- Stack: {caps.get('detected_stack') or 'unknown'}")
    print(f"- Language: {caps.get('language') or 'unknown'}")
    print(f"- Verification: {'available' if caps.get('verification_available', False) else 'unavailable'}")
    print(f"- Test command: {caps.get('test_command') or 'none'}")
    print(f"- Confidence: {caps.get('confidence', 'low')}")
    print(f"- Reason: {caps.get('reason', '')}")
    print("")
    print("Integrations:")
    print(f"- Aegis API key: {'configured' if aegis_key_configured else 'missing'}")
    print(f"- SLL: {'available' if sll.get('available', False) else 'unavailable'}")
    print(f"- Patch provider: {provider_state}")
    print("")
    print("State:")
    print(f"- Latest run: {'found' if latest.exists() else 'missing'}")
    print(f"- Backups: {len(backups)}")
    return 0


def handle_onboard(argv: Sequence[str]) -> int:
    parser = _build_onboard_parser()
    args = parser.parse_args(list(argv))
    email = str(args.email) if args.email is not None else input("Email: ").strip()
    if not email:
        print("Email is required.")
        return 2
    result = run_onboard(email=email, cwd=Path.cwd())
    if result.get("success", False):
        print("Aegis onboarding complete.")
        print("API key saved locally.")
        print("Aegis control is auto-enabled when AEGIS_API_KEY is configured (unless disabled in aegis.control_enabled).")
        return 0
    if "status_code" in result:
        print(f"Onboarding failed: {result.get('reason', 'network_error')} status={result.get('status_code')}")
        return 1
    print(f"Onboarding failed: {result.get('reason', 'network_error')}")
    return 1


def handle_context(argv: Sequence[str]) -> int:
    parser = _build_context_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.context_command == "refresh":
        result = refresh_context(cwd=cwd)
        print(format_context_refresh(result))
        return 0
    if args.context_command == "show":
        result = show_context(cwd=cwd)
        print(format_context_show(result))
        return 0 if result.get("exists", False) else 1
    parser.print_help()
    return 1


def _allow_runtime_or_print(
    cwd: Path,
    operation: str = "run_task",
    estimated_cost: float = 0.01,
    selected_mode: str | None = None,
    reason: str | None = None,
) -> bool:
    budget = load_budget(cwd)
    if not budget:
        return True
    if not can_spend(operation, estimated_cost, cwd):
        print("Budget control limit reached. Runtime execution skipped.")
        return False
    record_event(operation, estimated_cost, cwd, selected_mode=selected_mode, reason=reason)
    return True


def _write_budget_skipped_report(
    *,
    task: str,
    mode: str,
    dry_run: bool,
    cwd: Path,
    runtime_policy: dict[str, object],
    budget_state: dict[str, object],
) -> None:
    payload = {
        "task": task,
        "mode": mode,
        "dry_run": dry_run,
        "status": "budget_skipped",
        "notes": ["Runtime execution skipped by local budget control."],
        "commands_run": [],
        "test_attempts": [],
        "failures": {"failure_count": 0, "failed_tests": []},
        "initial_failures": {"failure_count": 0, "failed_tests": []},
        "final_failures": {"failure_count": 0, "failed_tests": []},
        "symptoms": [],
        "retry_policy": {
            "max_retries": 0,
            "allow_escalation": False,
            "retry_attempted": False,
            "retry_count": 0,
            "stopped_reason": "budget_skipped",
        },
        "patch_plan": {"strategy": "Skipped due to budget control.", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {"attempted": False, "available": False, "path": None, "error": None, "preview": ""},
        "patch_quality": None,
        "verification": {"available": False, "test_command": None, "detected_stack": None, "reason": "budget_skipped"},
        "runtime_policy": runtime_policy,
        "budget_state": budget_state,
        "project_context": {"available": False, "included_paths": [], "total_chars": 0},
        "adapter": {
            "mode": "local",
            "aegis_client_available": False,
            "control_requested": False,
            "control_status": "disabled",
            "control_reason": "budget_skipped",
            "execution": "local",
            "mutation": "confirm_only",
            "fallback_reason": "budget_skipped",
            "error_type": None,
            "error_message": None,
        },
        "aegis_impact": {"used": False, "action_count": 0, "override_applied": False, "fallback_used": True},
        "selected_model_tier": "mid",
        "selected_model": "unknown",
    }
    write_reports(payload, cwd=cwd)


def handle_budget(argv: Sequence[str]) -> int:
    parser = _build_budget_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.budget_command == "set":
        data = set_budget(float(args.amount), cwd=cwd)
        print(f"Budget set: ${float(data['limit']):.2f}")
        print("This budget controls runtime behavior, not actual API cost.")
        return 0
    if args.budget_command == "status":
        data = load_budget(cwd=cwd)
        if not data:
            print("Budget (control): not set")
            return 0
        limit = float(data.get("limit", 0.0) or 0.0)
        spent = float(data.get("spent_estimate", 0.0) or 0.0)
        remaining = max(0.0, limit - spent)
        print("Budget (control):")
        print(f"- Total: ${limit:.2f}")
        print(f"- Remaining: ${remaining:.2f}")
        print("Note: This budget influences runtime mode, not real spending.")
        return 0
    if args.budget_command == "clear":
        clear_budget(cwd=cwd)
        print("Budget cleared.")
        return 0
    parser.print_help()
    return 1


def handle_policy(argv: Sequence[str]) -> int:
    parser = _build_policy_parser()
    args = parser.parse_args(list(argv))
    if args.policy_command == "status":
        status = build_policy_status(cwd=Path.cwd())
        print(format_policy_status(status))
        return 0
    parser.print_help()
    return 1


def handle_provider(argv: Sequence[str]) -> int:
    parser = _build_provider_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.provider_command == "status":
        cfg = load_config(cwd)
        print("Provider configuration:")
        print(f"- cheap: {cfg.models.cheap}")
        print(f"- mid: {cfg.models.mid}")
        print(f"- premium: {cfg.models.premium}")
        return 0
    if args.provider_command == "model":
        tier = str(args.tier)
        value = str(args.value)
        if tier not in {"cheap", "mid", "premium"}:
            print("Error: invalid tier")
            return 2
        if ":" not in value:
            print("Error: invalid model format")
            return 2
        result = update_model_tier(tier=tier, value=value, cwd=cwd)
        print("Model updated:")
        print(f"- {result.get('tier', tier)} -> {result.get('value', value)}")
        return 0
    if args.provider_command == "list":
        print("Available presets:")
        for name in PRESETS:
            print(f"- {name}")
        return 0
    if args.provider_command == "detect":
        detection = detect_available_providers(cwd)
        print("Provider detection:")
        for item in detection.get("providers", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("key", ""))
            available = bool(item.get("available", False))
            presets = item.get("presets", [])
            preset_text = ", ".join(str(p) for p in presets) if isinstance(presets, list) else ""
            print(f"- {key}: {'found' if available else 'missing'}")
            print(f"  presets: {preset_text}")
        recommended = detection.get("recommended_preset")
        print(f"Recommended preset: {recommended if recommended else 'none'}")
        return 0
    if args.provider_command == "preset":
        preset_name = str(args.name)
        result = apply_preset(preset_name, cwd=cwd)
        if not result.get("applied", False):
            print("Error: unknown preset")
            return 2
        models = PRESETS[preset_name]
        print(f"Preset applied: {preset_name}")
        print(f"- cheap -> {models['cheap']}")
        print(f"- mid -> {models['mid']}")
        print(f"- premium -> {models['premium']}")
        return 0
    parser.print_help()
    return 1


def handle_keys(argv: Sequence[str]) -> int:
    parser = _build_keys_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    def _scope_from_args(parsed: object) -> str:
        if bool(getattr(parsed, "global_scope", False)):
            return "global"
        return "project"

    if args.keys_command == "set":
        scope = _scope_from_args(args)
        key_name = str(args.name).upper()
        existing = list_scoped_keys(cwd).get(scope, {}).get(key_name)
        if existing and not bool(args.yes):
            if not sys.stdin.isatty():
                print(f"Key {key_name} already exists in {scope} scope. Use --yes to overwrite in non-interactive mode.")
                return 2
            confirm = input(f"Key {key_name} already exists in {scope} scope. Overwrite? (y/N) ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return 0
        value = args.value
        if value is None:
            if not sys.stdin.isatty():
                print(f"Missing value for {key_name}. Provide VALUE or run interactively.")
                return 2
            value = getpass.getpass(f"Enter value for {key_name}: ")
        if not str(value).strip():
            print("Error: empty key value is not allowed.")
            return 2
        result = set_key(args.name, str(value), cwd=cwd, scope=scope)
        print(f"Stored {result.get('name', key_name)}: {mask_key(str(value))}")
        print(f"Scope: {scope}")
        return 0
    if args.keys_command == "clear":
        scope = _scope_from_args(args)
        result = clear_key(args.name, cwd=cwd, scope=scope)
        name = str(result.get("name", str(args.name).upper()))
        if result.get("cleared", False):
            print(f"Key cleared: {name} ({scope})")
            return 0
        print(f"Key not found: {name}")
        return 0
    if args.keys_command == "list":
        data = list_scoped_keys(cwd)
        print("GLOBAL:")
        for name in sorted(data.get("global", {}).keys()):
            print(f"- {name}: {mask_key(str(data['global'][name]))}")
        if not data.get("global"):
            print("- none")
        print("PROJECT:")
        for name in sorted(data.get("project", {}).keys()):
            print(f"- {name}: {mask_key(str(data['project'][name]))}")
        if not data.get("project"):
            print("- none")
        return 0
    if args.keys_command == "status":
        data = get_secrets_status(cwd=cwd)
        print("KEY                SOURCE      PRESENT")
        for item in data.get("keys", []):
            name = str(item.get("name", ""))
            source = str(item.get("source", "missing"))
            present = "yes" if bool(item.get("present", False)) else "no"
            print(f"{name:<18} {source:<10} {present}")
        return 0
    parser.print_help()
    return 1


def handle_workspace(argv: Sequence[str]) -> int:
    parser = _build_workspace_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.workspace_command == "init":
        init_workspace(cwd=cwd)
        print("Workspace initialized: .aegis/workspace.json")
        return 0
    if args.workspace_command == "add":
        result = add_project(Path(args.path), cwd=cwd)
        if result.get("added", False):
            print(f"Added: {Path(args.path).resolve()}")
            return 0
        reason = str(result.get("reason", ""))
        if reason == "already exists":
            print("Error: already exists")
            return 1
        if reason == "path does not exist":
            print("Error: path does not exist")
            return 1
        print("Error: failed to add project")
        return 1
    if args.workspace_command == "remove":
        result = remove_project(Path(args.path), cwd=cwd)
        if result.get("removed", False):
            print(f"Removed: {Path(args.path).resolve()}")
            return 0
        reason = str(result.get("reason", ""))
        if reason == "no_workspace":
            print("No workspace found. Run `aegis-code workspace init`.")
            return 1
        if reason == "not_found":
            print("Error: project not found")
            return 2
        print("Error: failed to remove project")
        return 2
    if args.workspace_command == "status":
        if not args.detailed:
            status = get_status(cwd=cwd)
            if not status.get("exists", False):
                print("No workspace found. Run `aegis-code workspace init`.")
                return 1
            print("Workspace:")
            print(f"- Projects: {status.get('project_count', 0)}")
            for item in status.get("projects", []):
                print("")
                print(f"- {item.get('name', '')}")
                print(f"  path: {item.get('path', '')}")
                print(f"  exists: {'true' if item.get('exists', False) else 'false'}")
            return 0

        status = get_detailed_status(cwd=cwd)
        if not status.get("exists", False):
            print("No workspace found. Run `aegis-code workspace init`.")
            return 1
        print("Workspace:")
        print(f"- Projects: {status.get('project_count', 0)}")
        for item in status.get("projects", []):
            print("")
            print(f"- {item.get('name', '')}")
            print(f"  path: {item.get('path', '')}")
            print(f"  exists: {'true' if item.get('exists', False) else 'false'}")
            if item.get("exists", False):
                print(f"  config: {'found' if item.get('config', False) else 'missing'}")
                print(f"  budget: {'set' if item.get('budget', False) else 'not set'}")
                print(f"  context: {'available' if item.get('context', False) else 'missing'}")
                print(f"  latest run: {'found' if item.get('latest_run', False) else 'missing'}")
                print(f"  mode: {item.get('mode', 'unknown')}")
        return 0
    if args.workspace_command == "overview":
        overview = get_workspace_overview(cwd=cwd)
        if not overview.get("exists", False):
            print("No workspace found. Run `aegis-code workspace init`.")
            return 1
        print("Workspace Overview:")
        print(f"- Projects: {overview.get('total', 0)}")
        print(f"- Available: {overview.get('available', 0)}")
        print(f"- Missing: {overview.get('missing', 0)}")
        print(f"- Configured: {overview.get('configured', 0)}")
        print(f"- Budgets set: {overview.get('budget', 0)}")
        print(f"- Context ready: {overview.get('context', 0)}")
        print(f"- Latest runs: {overview.get('latest_run', 0)}")
        return 0
    if args.workspace_command == "compare":
        result = compare_workspace_runs(cwd=cwd)
        if not result.get("exists", False):
            print("No workspace found. Run `aegis-code workspace init`.")
            return 1
        print("Workspace Compare:")
        print(f"- Projects: {result.get('projects', 0)}")
        print(f"- With runs: {result.get('total_runs', 0)}")
        print(f"- Missing runs: {result.get('missing_runs', 0)}")
        print(f"- Skipped (missing path): {result.get('skipped_missing', 0)}")
        print(f"- Passed: {result.get('passed', 0)}")
        print(f"- Failed: {result.get('failed', 0)}")
        print(f"- Aegis mode: {result.get('aegis_mode', 0)}")
        print(f"- Local mode: {result.get('local_mode', 0)}")
        return 0
    if args.workspace_command == "refresh-context":
        result = refresh_workspace_context(cwd=cwd)
        if not result.get("exists", False):
            print("No workspace found. Run `aegis-code workspace init`.")
            return 1
        print("Workspace context refresh:")
        print(f"- Projects: {result.get('total', 0)}")
        print(f"- Refreshed: {result.get('refreshed', 0)}")
        print(f"- Skipped (missing): {result.get('skipped_missing', 0)}")
        return 0
    if args.workspace_command == "run":
        if args.dry_run:
            preview = preview_workspace_run(task=args.task, cwd=cwd)
            if not preview.get("exists", False):
                print("No workspace found. Run `aegis-code workspace init`.")
                return 1
            print("Workspace run preview:")
            print(f"- Task: {preview.get('task', '')}")
            print(f"- Projects: {preview.get('would_run', 0)}")
            print(f"- Skipped (missing): {preview.get('skipped_missing', 0)}")
            for item in preview.get("projects", []):
                print("")
                print(f"- {item.get('name', '')}")
                print(f"  path: {item.get('path', '')}")
                print(f"  action: {item.get('action', '')}")
            return 0

        if args.confirm:
            result = run_workspace_task(task=args.task, cwd=cwd)
            if not result.get("exists", False):
                print("No workspace found. Run `aegis-code workspace init`.")
                return 1
            print("Workspace run:")
            print(f"- Task: {result.get('task', '')}")
            print(f"- Executed: {result.get('executed', 0)}")
            print(f"- Skipped (missing): {result.get('skipped_missing', 0)}")
            print(f"- Skipped (budget): {result.get('skipped_budget', 0)}")
            for item in result.get("projects", []):
                print("")
                print(f"- {item.get('name', '')}")
                print(f"  path: {item.get('path', '')}")
                print(f"  mode: {item.get('mode', '')}")
                print(f"  status: {item.get('status', '')}")
            return 0

        print("Error: must specify either --dry-run or --confirm")
        return 2
    parser.print_help()
    return 1


def handle_apply(argv: Sequence[str]) -> int:
    parser = _build_apply_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.check:
        path = Path(args.check)
        try:
            result = check_patch_file(path, cwd=cwd)
        except FileNotFoundError:
            print(f"Diff file not found: {path}")
            print("Run a failing task with --propose-patch first, or provide a valid diff path.")
            return 2
        except Exception as exc:
            print(f"Patch check failed: {exc}")
            return 2
        print(format_apply_check_result(result))
        return 0

    if not args.path:
        print("Patch application requires --confirm. Use --check to preview without modifying files.")
        return 2

    if not args.confirm:
        path = Path(args.path)
        try:
            result = check_patch_file(path, cwd=cwd)
        except FileNotFoundError:
            print(f"Diff file not found: {path}")
            print("Run a failing task with --propose-patch first, or provide a valid diff path.")
            return 2
        except Exception as exc:
            print(f"Patch preview failed: {exc}")
            return 2
        summary = result.get("summary", {})
        print(f"Patch preview: {result.get('path')}")
        print(f"Valid: {result.get('valid', False)}")
        print(f"Files: {summary.get('file_count', 0)}")
        print(f"Hunks: {summary.get('hunk_count', 0)}")
        print(f"Additions: {summary.get('additions', 0)}")
        print(f"Deletions: {summary.get('deletions', 0)}")
        print(f"Apply blocked: {result.get('apply_blocked', False)}")
        blockers = result.get("apply_block_reasons", [])
        if blockers:
            print("Apply block reasons:")
            for item in blockers:
                print(f"- {item}")
        print("Warnings:")
        warnings = result.get("warnings", [])
        if warnings:
            for item in warnings:
                print(f"- {item}")
        else:
            print("- none")
        print("Applied: false")
        print("Patch application requires --confirm.")
        print("Use --confirm to apply this patch.")
        return 1

    path = Path(args.path)
    result = apply_patch_file(path, cwd=cwd)
    print(format_apply_result(result))
    return 0 if result.get("applied", False) else 2


def handle_backups(argv: Sequence[str]) -> int:
    parser = _build_backups_parser()
    parser.parse_args(list(argv))
    result = list_backups(cwd=Path.cwd())
    backups = result.get("backups", [])
    if not backups:
        print("No backups found.")
        return 0
    print("Backups:")
    for item in backups:
        print(f"- {item.get('id')}")
        for file_path in item.get("files", []):
            print(f"  - {file_path}")
    return 0


def handle_restore(argv: Sequence[str]) -> int:
    parser = _build_restore_parser()
    args = parser.parse_args(list(argv))
    result = restore_backup(args.backup_id, cwd=Path.cwd())
    print(f"Restore: {result.get('backup_id')}")
    print(f"Restored: {result.get('restored', False)}")
    files = result.get("files", [])
    print("Files:")
    if files:
        for file_path in files:
            print(f"- {file_path}")
    else:
        print("- none")
    errors = result.get("errors", [])
    if errors:
        print("Errors:")
        for err in errors:
            print(f"- {err}")
    return 0 if result.get("restored", False) else 2


def handle_check_sll(argv: Sequence[str]) -> int:
    parser = _build_check_sll_parser()
    parser.parse_args(list(argv))
    status = check_sll_available()
    print(f"SLL available: {'true' if status.get('available', False) else 'false'}")
    print(f"Import path: {status.get('import_path', 'structural_language_lab')}")
    if status.get("error"):
        print(f"Error: {status.get('error')}")
    return 0


def handle_task(argv: Sequence[str]) -> int:
    parser = _build_task_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    cfg = load_config(cwd)
    base_mode = args.mode or cfg.mode
    final_mode = select_runtime_mode(base_mode, cwd=cwd)
    reason = get_mode_reason(base_mode, final_mode, cwd=cwd)
    if not _allow_runtime_or_print(cwd, selected_mode=final_mode, reason=reason):
        if not args.no_report:
            budget_state = get_budget_state(cwd=cwd)
            runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=cwd)
            _write_budget_skipped_report(
                task=args.task,
                mode=final_mode,
                dry_run=bool(args.dry_run),
                cwd=cwd,
                runtime_policy=runtime_policy,
                budget_state=budget_state,
            )
        return 0
    project_context = load_runtime_context(cwd=cwd)
    budget_state = get_budget_state(cwd=cwd)
    runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=cwd)
    if not args.quiet:
        print("Aegis Code: controlled execution...")
    progress_state = {"i": 0}
    heartbeat_state = {"active": False, "last_non_tty_elapsed": -10, "current_message": ""}
    progress_labels = [
        "loading config",
        "resolving keys",
        "running verification command",
        "requesting Aegis guidance",
        "building task context",
        "generating provider diff",
        "validating diff",
        "attempting repair",
        "attempting regeneration",
        "checking syntax of proposed Python changes",
        "writing report",
    ]

    def _progress_cb(message: str) -> None:
        if args.quiet:
            return
        text = str(message)
        if text.startswith("  waiting on provider"):
            elapsed_match = re.search(r"\((\d+)s\)\s*$", text)
            elapsed = int(elapsed_match.group(1)) if elapsed_match else 0
            step = max(1, progress_state["i"])
            total = len(progress_labels)
            stage = heartbeat_state["current_message"] or "running provider call"
            if sys.stdout.isatty():
                sys.stdout.write(f"\r[{step}/{total}] {stage}... waiting {elapsed}s")
                sys.stdout.flush()
                heartbeat_state["active"] = True
            elif elapsed - int(heartbeat_state["last_non_tty_elapsed"]) >= 10:
                print(f"[{step}/{total}] {stage}... waiting {elapsed}s")
                heartbeat_state["last_non_tty_elapsed"] = elapsed
            return
        if heartbeat_state["active"]:
            print("")
            heartbeat_state["active"] = False
        heartbeat_state["last_non_tty_elapsed"] = -10
        progress_state["i"] += 1
        step = progress_state["i"]
        total = len(progress_labels)
        heartbeat_state["current_message"] = text
        print(f"[{step}/{total}] {text}")

    options = TaskOptions(
        task=args.task,
        budget=args.budget,
        mode=final_mode,
        dry_run=args.dry_run,
        analyze_failures=args.analyze_failures,
        propose_patch=args.propose_patch,
        session=args.session,
        no_report=args.no_report,
        project_context=project_context,
        budget_state=budget_state,
        runtime_policy=runtime_policy,
        progress_callback=_progress_cb,
    )
    payload = run_task(options=options, cwd=cwd)
    if heartbeat_state["active"] and not args.quiet:
        print("")

    print("Aegis Code: controlled execution with proposal-only patch diffs and patch-quality scoring.")
    print(f"Task: {payload['task']}")
    print(f"Selected runtime mode: {final_mode}")
    print(f"Mode: {payload['mode']}")
    print(f"Dry run: {payload['dry_run']}")
    print(
        "Selected model: "
        f"{payload.get('selected_model_tier', 'mid')} -> {payload.get('selected_model', 'unknown')}"
    )
    print(f"Status: {payload['status']}")
    failure_count = payload.get("failures", {}).get("failure_count", 0)
    symptoms = payload.get("symptoms", [])
    retry_policy = payload.get("retry_policy", {})
    has_patch_plan = bool(payload.get("patch_plan", {}).get("proposed_changes"))
    patch_diff = payload.get("patch_diff", {})
    patch_quality = payload.get("patch_quality")
    sll_analysis = payload.get("sll_analysis", {})
    print(f"Failure count: {failure_count}")
    verification = payload.get("verification", {}) or {}
    print(
        "Verification: "
        f"available={verification.get('available', False)} command={verification.get('test_command', 'n/a')}"
    )
    print(f"Symptoms: {', '.join(symptoms) if symptoms else 'none'}")
    print(f"SLL available: {sll_analysis.get('available', False)}")
    print(
        "Retry attempted/count: "
        f"{retry_policy.get('retry_attempted', False)}/{retry_policy.get('retry_count', 0)}"
    )
    print(f"Patch plan available: {has_patch_plan}")
    print(f"Patch diff attempted: {patch_diff.get('attempted', False)}")
    print(f"Regeneration attempted: {patch_diff.get('regeneration_attempted', False)}")
    if patch_diff.get("regeneration_attempted", False):
        print(f"Aegis corrective control: {patch_diff.get('corrective_control_status', 'not_triggered')}")
    if bool(payload.get("task_driven_patch_proposal", False)):
        print("Patch proposal generated from task intent (no test failures).")
    print(f"Patch diff status: {patch_diff.get('status', 'skipped')}")
    if patch_diff.get("path"):
        print(f"Patch diff written: {patch_diff.get('path')}")
    if patch_diff.get("invalid_diff_path"):
        print(f"Invalid diff written: {patch_diff.get('invalid_diff_path')}")
    if patch_diff.get("error"):
        print(f"Patch diff error: {patch_diff.get('error')}")
    if str(patch_diff.get("status", "")) == "invalid":
        print("Patch quality: invalid (not evaluated)")
    elif patch_quality:
        quality_state = []
        if patch_quality.get("grounded", False):
            quality_state.append("grounded")
        if patch_quality.get("relevant_files", False):
            quality_state.append("relevant")
        if quality_state:
            print(
                f"Patch quality: {patch_quality.get('confidence', 0.0)} ({', '.join(quality_state)})"
            )
        else:
            issues = patch_quality.get("issues", [])
            print(
                f"Patch quality: low (issues: {', '.join(str(item) for item in issues) if issues else 'unknown'})"
            )
    if not args.no_report:
        paths = project_paths()
        print(f"Report JSON: {paths['latest_json']}")
        print(f"Report MD: {paths['latest_md']}")
    print(format_runtime_control_summary(payload.get("runtime_policy"), payload.get("budget_state"), payload.get("project_context")))
    print(_format_adapter_summary(payload.get("adapter")))
    _print_aegis_impact_if_relevant(payload)
    _print_aegis_usage_if_available(payload, cwd)
    return 0


def handle_fix(argv: Sequence[str]) -> int:
    parser = _build_fix_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    cfg = load_config(cwd)
    verification_command = cfg.commands.test.strip()
    if not verification_command:
        print("Fix summary:")
        print("- Verification command: none")
        print("- Failure count: n/a")
        print("No test command detected. Aegis Code can inspect and plan, but cannot verify a fix yet.")
        print("Next: run `aegis-code init` or set `commands.test` in `.aegis/aegis-code.yml`.")
        return 2

    base_mode = cfg.mode
    final_mode = select_runtime_mode(base_mode, cwd=cwd)
    options = TaskOptions(
        task="triage current test failures",
        mode=final_mode,
        propose_patch=True,
        no_report=False,
        project_context={},
    )
    reason = get_mode_reason(base_mode, final_mode, cwd=cwd)
    if not _allow_runtime_or_print(cwd, selected_mode=final_mode, reason=reason):
        return 0
    options.project_context = load_runtime_context(cwd=cwd)
    options.budget_state = get_budget_state(cwd=cwd)
    options.runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=cwd)
    payload = run_task(options=options, cwd=cwd)
    print(format_runtime_control_summary(options.runtime_policy, options.budget_state, options.project_context))
    print(_format_adapter_summary(payload.get("adapter")))
    _print_aegis_impact_if_relevant(payload)
    _print_aegis_usage_if_available(payload, cwd)

    latest = project_paths()["latest_json"]
    if not latest.exists():
        print("No patch proposal available. Use report to inspect failures.")
        return 2
    payload = json.loads(latest.read_text(encoding="utf-8"))
    failures = payload.get("failures", {})
    failure_count = int(failures.get("failure_count", 0) or 0)
    if failure_count == 0:
        print("Fix summary:")
        print(f"- Verification command: {verification_command}")
        print(f"- Failure count: {failure_count}")
        print("Tests passed. No action required.")
        print("Next: run `aegis-code report` for details.")
        return 0

    patch_diff = payload.get("patch_diff", {})
    diff_path = patch_diff.get("path")
    if not patch_diff.get("available", False) or not diff_path:
        print("Fix summary:")
        print(f"- Verification command: {verification_command}")
        print(f"- Failure count: {failure_count}")
        print("- Patch diff path: none")
        print("No patch proposal available. Use report to inspect failures.")
        print("Next: run `aegis-code report`.")
        return 2

    diff_file = Path(str(diff_path))
    if not diff_file.exists():
        print("No patch proposal available. Use report to inspect failures.")
        return 2
    inspected = inspect_diff(diff_file.read_text(encoding="utf-8"), cwd=Path.cwd())
    summary = inspected.get("summary", {})
    patch_quality = payload.get("patch_quality")

    print("Fix summary:")
    print(f"- Verification command: {verification_command}")
    print(f"- Failure count: {failure_count}")
    print(f"- Patch diff path: {diff_path}")
    print("Patch proposal:")
    print(f"- Files: {summary.get('file_count', 0)}")
    print(f"- Changes: +{summary.get('additions', 0)} / -{summary.get('deletions', 0)}")
    if patch_quality:
        print(f"- Quality: {patch_quality.get('confidence', 0.0)}")
    else:
        print("- Quality: n/a")

    if not args.confirm:
        print(f"Preview available. Use `aegis-code apply {diff_path}` to inspect.")
        print("Use `aegis-code fix --confirm` to apply this patch.")
        return 1

    apply_result = apply_patch_file(diff_file, cwd=Path.cwd())
    print("Apply result:")
    print(format_apply_result(apply_result))
    if not apply_result.get("applied", False):
        print("Next: run `aegis-code apply --check .aegis/runs/latest.diff` and `aegis-code report`.")
        return 2

    result = run_configured_tests(verification_command, cwd=Path.cwd())
    if result.status == "ok" and result.exit_code == 0:
        print("Post-apply tests passed.")
        print("Next: run `aegis-code report` and `aegis-code status`.")
        return 0
    print("Post-apply tests are still failing.")
    print("Next: run `aegis-code report` to inspect remaining failures.")
    return 2


def handle_next(argv: Sequence[str]) -> int:
    parser = _build_next_parser()
    parser.parse_args(list(argv))
    payload = build_next_actions(cwd=Path.cwd())
    print(format_next_actions(payload))
    return 0


def handle_usage(argv: Sequence[str]) -> int:
    parser = _build_usage_parser()
    parser.parse_args(list(argv))
    cwd = Path.cwd()
    usage_path = cwd / ".aegis" / "usage.json"
    if not usage_path.exists():
        print("No Aegis usage recorded yet.")
        return 0
    usage = load_usage(cwd)
    print("Aegis Usage:")
    print(f"- Attempts: {int(usage.get('calls', 0) or 0)}")
    print(f"- Successful: {int(usage.get('successful', 0) or 0)}")
    print(f"- Fallbacks: {int(usage.get('fallbacks', 0) or 0)}")
    print(f"- Actions applied: {int(usage.get('actions_applied', 0) or 0)}")
    print(f"- Last used: {usage.get('last_used') or 'n/a'}")
    warning = get_usage_warning(usage)
    if warning:
        limit = int(warning.get("limit", 100) or 100)
        if warning.get("type") == "approaching_limit":
            print(f"⚠ Approaching Aegis usage limit ({limit} calls)")
        elif warning.get("type") == "limit_reached":
            print(f"⚠ Aegis usage limit reached ({limit} calls)")
            print("Aegis will continue to run, but limits may apply in future versions.")
    return 0


def handle_setup(argv: Sequence[str]) -> int:
    parser = _build_setup_parser()
    args = parser.parse_args(list(argv))
    if args.check:
        status = check_setup(Path.cwd())
        if not bool(status.get("initialized", False)):
            print("No project initialized. Run `aegis-code setup`.")
            return 2
        print("Setup Check:")
        print(f"- Project initialized: {'true' if bool(status.get('initialized', False)) else 'false'}")
        print(f"- Aegis key: {'set' if bool(status.get('aegis_key', False)) else 'missing'}")
        print(f"- Aegis control: {status.get('aegis_control_status', 'disabled')}")
        print(f"- Provider key: {'found' if bool(status.get('provider_key', False)) else 'missing'}")
        print(f"- Provider preset: {'configured' if bool(status.get('provider_preset', False)) else 'missing'}")
        print(f"- Context: {'available' if bool(status.get('context_available', False)) else 'missing'}")
        print(f"- Latest run: {'found' if bool(status.get('latest_run', False)) else 'missing'}")
        print(f"- Verification: {'available' if bool(status.get('verification_available', False)) else 'missing'}")

        fully_ready = all(
            bool(status.get(key, False))
            for key in (
                "initialized",
                "aegis_key",
                "provider_key",
                "provider_preset",
                "context_available",
                "verification_available",
            )
        )
        return 0 if fully_ready else 1

    result = run_setup(
        cwd=Path.cwd(),
        email=args.email,
        skip_aegis=bool(args.skip_aegis),
        skip_provider=bool(args.skip_provider),
        skip_first_run=bool(args.skip_first_run),
        assume_yes=bool(args.yes),
    )

    aegis_result = result.get("aegis", {}) if isinstance(result.get("aegis"), dict) else {}
    provider_result = result.get("provider", {}) if isinstance(result.get("provider"), dict) else {}
    first_run_result = result.get("first_run", {}) if isinstance(result.get("first_run"), dict) else {}

    if bool(aegis_result.get("success", False)):
        if str(aegis_result.get("reason", "")) == "already_configured":
            aegis_status = "already configured"
        else:
            aegis_status = "connected"
    elif str(aegis_result.get("reason", "")) in {"skipped", "email_required"}:
        aegis_status = "skipped"
    else:
        aegis_status = "failed"

    applied_preset = provider_result.get("applied_preset")
    provider_summary = str(applied_preset) if applied_preset else "none"
    first_status = first_run_result.get("status")
    first_summary = str(first_status) if first_status else "skipped"

    print("Aegis Code setup")
    print("")
    print("Setup complete.")
    print(f"- Initialized: {'true' if bool(result.get('initialized', False)) else 'false'}")
    print(f"- Aegis: {aegis_status}")
    print(f"- Provider preset: {provider_summary}")
    print(f"- First run: {first_summary}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(argv) if argv is not None else None
    if args is None:
        import sys

        args = sys.argv[1:]

    if not args:
        _build_task_parser().print_help()
        return 1

    if args[0] == "--check-sll":
        return handle_check_sll(args[1:])

    command = args[0]
    if command == "init":
        return handle_init(args[1:])
    if command == "report":
        return handle_report(args[1:])
    if command == "status":
        return handle_status(args[1:])
    if command == "compare":
        return handle_compare(args[1:])
    if command == "overview":
        return handle_overview(args[1:])
    if command == "maintain":
        return handle_maintain(args[1:])
    if command == "create":
        return handle_create(args[1:])
    if command == "doctor":
        return handle_doctor(args[1:])
    if command == "onboard":
        return handle_onboard(args[1:])
    if command == "context":
        return handle_context(args[1:])
    if command == "budget":
        return handle_budget(args[1:])
    if command == "policy":
        return handle_policy(args[1:])
    if command == "provider":
        return handle_provider(args[1:])
    if command == "keys":
        return handle_keys(args[1:])
    if command == "workspace":
        return handle_workspace(args[1:])
    if command == "apply":
        return handle_apply(args[1:])
    if command == "backups":
        return handle_backups(args[1:])
    if command == "restore":
        return handle_restore(args[1:])
    if command == "fix":
        return handle_fix(args[1:])
    if command == "next":
        return handle_next(args[1:])
    if command == "usage":
        return handle_usage(args[1:])
    if command == "setup":
        return handle_setup(args[1:])
    return handle_task(args)


if __name__ == "__main__":
    raise SystemExit(main())

