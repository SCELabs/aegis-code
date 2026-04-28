from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Sequence

from aegis_code.budget import can_spend, clear_budget, get_budget_state, load_budget, record_event, set_budget
from aegis_code.config import load_config
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
from aegis_code.overview import build_overview, format_overview
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
from aegis_code.config import ensure_project_files, project_paths
from aegis_code.report import read_latest_markdown
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.scaffolds import list_stacks
from aegis_code.sll_adapter import check_sll_available
from aegis_code.tools.tests import run_configured_tests


def _build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code init")
    parser.add_argument("--force", action="store_true", help="Overwrite default project files.")
    return parser


def _build_report_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code report")


def _build_status_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code status")


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
    run_task(
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
        print("Budget limit reached. Skipping Aegis runtime.")
        return False
    record_event(operation, estimated_cost, cwd, selected_mode=selected_mode, reason=reason)
    return True


def handle_budget(argv: Sequence[str]) -> int:
    parser = _build_budget_parser()
    args = parser.parse_args(list(argv))
    cwd = Path.cwd()
    if args.budget_command == "set":
        data = set_budget(float(args.amount), cwd=cwd)
        print(f"Budget set: limit={data['limit']} spent_estimate={data['spent_estimate']} currency={data['currency']}")
        return 0
    if args.budget_command == "status":
        data = load_budget(cwd=cwd)
        if not data:
            print("Budget: not set")
            return 0
        print(
            f"Budget: limit={data.get('limit', 0.0)} spent_estimate={data.get('spent_estimate', 0.0)} "
            f"currency={data.get('currency', 'USD')}"
        )
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
        return 0
    project_context = load_runtime_context(cwd=cwd)
    budget_state = get_budget_state(cwd=cwd)
    runtime_policy = build_runtime_policy_payload(base_mode, final_mode, cwd=cwd)
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
    )
    payload = run_task(options=options, cwd=cwd)

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
    if patch_diff.get("available", False):
        print("Patch diff status: generated")
    elif patch_diff.get("attempted", False):
        print("Patch diff status: unavailable")
    else:
        print("Patch diff status: skipped")
    if patch_diff.get("path"):
        print(f"Patch diff written: {patch_diff.get('path')}")
    if patch_diff.get("error"):
        print(f"Patch diff error: {patch_diff.get('error')}")
    if patch_quality:
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
    run_task(options=options, cwd=cwd)
    print(format_runtime_control_summary(options.runtime_policy, options.budget_state, options.project_context))

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
    if command == "overview":
        return handle_overview(args[1:])
    if command == "maintain":
        return handle_maintain(args[1:])
    if command == "create":
        return handle_create(args[1:])
    if command == "doctor":
        return handle_doctor(args[1:])
    if command == "context":
        return handle_context(args[1:])
    if command == "budget":
        return handle_budget(args[1:])
    if command == "policy":
        return handle_policy(args[1:])
    if command == "apply":
        return handle_apply(args[1:])
    if command == "backups":
        return handle_backups(args[1:])
    if command == "restore":
        return handle_restore(args[1:])
    if command == "fix":
        return handle_fix(args[1:])
    return handle_task(args)


if __name__ == "__main__":
    raise SystemExit(main())
