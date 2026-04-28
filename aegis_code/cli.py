from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from aegis_code.config import load_config
from aegis_code.patches.apply_check import check_patch_file, format_apply_check_result
from aegis_code.patches.backups import list_backups, restore_backup
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.patch_applier import apply_patch_file, format_apply_result
from aegis_code.config import ensure_project_files, project_paths
from aegis_code.report import read_latest_markdown
from aegis_code.runtime import TaskOptions, run_task
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

    print("Status:")
    print(f"- Task: {payload.get('task', '')}")
    print(f"- Run status: {payload.get('status', '')}")
    print(f"- Failure count: {payload.get('failures', {}).get('failure_count', 0)}")
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

    print(
        "Aegis Code v0.5 runs a controlled execution loop with proposal-only patch diffs and deterministic diff quality scoring."
    )
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
    patch_quality = payload.get("patch_quality")
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
    return 0


def handle_fix(argv: Sequence[str]) -> int:
    parser = _build_fix_parser()
    args = parser.parse_args(list(argv))

    options = TaskOptions(
        task="triage current test failures",
        propose_patch=True,
        no_report=False,
    )
    run_task(options=options, cwd=Path.cwd())

    latest = project_paths()["latest_json"]
    if not latest.exists():
        print("No patch proposal available. Use report to inspect failures.")
        return 2
    payload = json.loads(latest.read_text(encoding="utf-8"))
    failures = payload.get("failures", {})
    failure_count = int(failures.get("failure_count", 0) or 0)
    if failure_count == 0:
        print("Tests passed. No action required.")
        return 0

    patch_diff = payload.get("patch_diff", {})
    diff_path = patch_diff.get("path")
    if not patch_diff.get("available", False) or not diff_path:
        print("No patch proposal available. Use report to inspect failures.")
        return 2

    diff_file = Path(str(diff_path))
    if not diff_file.exists():
        print("No patch proposal available. Use report to inspect failures.")
        return 2
    inspected = inspect_diff(diff_file.read_text(encoding="utf-8"), cwd=Path.cwd())
    summary = inspected.get("summary", {})
    patch_quality = payload.get("patch_quality")

    print("Patch proposal:")
    print(f"- Files: {summary.get('file_count', 0)}")
    print(f"- Changes: +{summary.get('additions', 0)} / -{summary.get('deletions', 0)}")
    if patch_quality:
        print(f"- Quality: {patch_quality.get('confidence', 0.0)}")
    else:
        print("- Quality: n/a")

    if not args.confirm:
        print(f"Preview available. Use aegis-code apply {diff_path} to inspect.")
        print("Use --confirm to apply this patch.")
        return 1

    apply_result = apply_patch_file(diff_file, cwd=Path.cwd())
    print(format_apply_result(apply_result))
    if not apply_result.get("applied", False):
        return 2

    cfg = load_config(Path.cwd())
    command = cfg.commands.test.strip()
    if not command:
        print("Patch applied. No configured test command to verify.")
        return 0
    result = run_configured_tests(command, cwd=Path.cwd())
    if result.status == "ok" and result.exit_code == 0:
        print("Post-apply tests passed.")
        return 0
    print("Post-apply tests are still failing.")
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
