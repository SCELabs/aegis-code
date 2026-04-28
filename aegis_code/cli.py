from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from aegis_code.config import ensure_project_files, project_paths
from aegis_code.report import read_latest_markdown
from aegis_code.runtime import TaskOptions, run_task
from aegis_code.sll_adapter import check_sll_available


def _build_init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aegis-code init")
    parser.add_argument("--force", action="store_true", help="Overwrite default project files.")
    return parser


def _build_report_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code report")


def _build_check_sll_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog="aegis-code --check-sll")


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
    created = ensure_project_files(force=args.force)
    paths = project_paths()
    print(f"Initialized: {paths['aegis_dir']}")
    print(f"Config: {paths['config_path']} ({'created' if created['config_created'] else 'kept'})")
    print(
        "Project model: "
        f"{paths['project_model_path']} ({'created' if created['project_model_created'] else 'kept'})"
    )
    print("v0.1 note: planning/reporting only. No file editing is performed.")
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
    options = TaskOptions(
        task=args.task,
        budget=args.budget,
        mode=args.mode,
        dry_run=args.dry_run,
        analyze_failures=args.analyze_failures,
        propose_patch=args.propose_patch,
        session=args.session,
        no_report=args.no_report,
    )
    payload = run_task(options=options, cwd=Path.cwd())

    print("Aegis Code v0.4: controlled execution with proposal-only patch diffs.")
    print(f"Task: {payload['task']}")
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
    sll_analysis = payload.get("sll_analysis", {})
    print(f"Failure count: {failure_count}")
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
    if not args.no_report:
        paths = project_paths()
        print(f"Report JSON: {paths['latest_json']}")
        print(f"Report MD: {paths['latest_md']}")
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
    return handle_task(args)


if __name__ == "__main__":
    raise SystemExit(main())
