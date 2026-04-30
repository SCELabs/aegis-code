from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
import json
import re
from pathlib import Path
from copy import deepcopy
from typing import Any

from aegis_code.aegis_client import AegisBackendClient, apply_resolved_aegis_env, client_from_env
from aegis_code.budget import BudgetState
from aegis_code.config import load_config
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.context.failure_context import build_failure_context
from aegis_code.context.repo_scan import scan_repo
from aegis_code.execution_loop import should_retry_tests, synthesize_symptoms
from aegis_code.models import CommandResult
from aegis_code.patches.diff_evaluator import evaluate_diff
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.diff_normalizer import normalize_unified_diff
from aegis_code.patches.diff_repair import repair_malformed_diff
from aegis_code.patches.diff_writer import (
    remove_latest_diff,
    remove_latest_invalid_diff,
    write_latest_diff,
    write_latest_invalid_diff,
)
from aegis_code.parsers.pytest_parser import parse_pytest_output
from aegis_code.planning.patch_generator import generate_patch_plan
from aegis_code.providers import generate_patch_diff
from aegis_code.report import write_reports
from aegis_code.routing import normalize_tier, resolve_model_for_tier
from aegis_code.secrets import list_scoped_keys, resolve_key, resolve_key_source
from aegis_code.sll_adapter import analyze_failures_sll
from aegis_code.tools.tests import run_configured_tests

_HUNK_RE = re.compile(r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@")


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
    aegis_guidance: dict[str, Any] | None = None


def _is_tests_passed(status: str, exit_code: int | None) -> bool:
    return status == "ok" and exit_code == 0


def is_constructive_task(task: str) -> bool:
    lowered = str(task or "").lower()
    if is_test_generation_task(lowered):
        return True

    positive = (
        "add",
        "create",
        "implement",
        "build",
        "write",
        "generate",
        "refactor",
        "update",
        "extend",
    )
    negative = ("run tests", "execute tests", "check tests", "analyze", "summarize", "explain")
    if any(token in lowered for token in negative):
        return False
    return any(token in lowered for token in positive)


def is_test_generation_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return False
    verification_only = ("run tests", "execute tests", "check tests")
    if any(phrase in lowered for phrase in verification_only):
        return False

    generation_phrases = (
        "add test",
        "add tests",
        "write test",
        "write tests",
        "generate test",
        "generate tests",
        "test for",
        "tests for",
        "coverage",
        "verify behavior",
        "assert",
    )
    return any(phrase in lowered for phrase in generation_phrases)


def _test_hint_path(task: str, context: dict[str, Any]) -> str:
    files = context.get("files", []) if isinstance(context, dict) else []
    for item in files:
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            if path.startswith("tests/") and path.endswith(".py"):
                return path

    tokens = [
        token
        for token in "".join(ch if ch.isalnum() else " " for ch in str(task or "").lower()).split()
        if token not in {"add", "write", "test", "tests", "for", "the", "a", "an", "to", "of", "and", "in"}
    ]
    base = tokens[0] if tokens else "task"
    return f"tests/test_{base}.py"


def _patch_diff_default() -> dict[str, Any]:
    return {
        "attempted": False,
        "available": False,
        "status": "skipped",
        "regenerated": False,
        "regeneration_attempted": False,
        "aegis_corrective_control_applied": False,
        "repair_attempted": False,
        "repair_applied": False,
        "repair_status": "not_attempted",
        "repair_reason": "not_attempted",
        "repair_error": None,
        "syntactic_valid": None,
        "syntactic_error": None,
        "corrective_control_status": "not_triggered",
        "corrective_control_reason": "not_triggered",
        "corrective_control_error": None,
        "provider": None,
        "model": None,
        "path": None,
        "error": None,
        "preview": "",
    }


def _is_ignored_path(path: Path) -> bool:
    parts = set(path.parts)
    ignored = {
        ".aegis",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "node_modules",
        "dist",
        "build",
    }
    if parts & ignored:
        return True
    return any(part.endswith(".egg-info") for part in path.parts)


def _read_context_file(path: Path, max_chars_per_file: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    if len(text) <= max_chars_per_file:
        return text
    return text[:max_chars_per_file].rstrip() + "\n[truncated]"


def build_task_context(cwd: Path) -> dict:
    root = cwd.resolve()
    max_files = 10
    max_chars_per_file = 6000
    selected: list[Path] = []

    entrypoints = [
        root / "src" / "main.py",
        root / "main.py",
        root / "cli.py",
        root / "app.py",
    ]
    for path in entrypoints:
        if path.exists() and path.is_file():
            selected.append(path)

    for path in sorted((root / "tests").rglob("*.py")) if (root / "tests").exists() else []:
        if len(selected) >= max_files:
            break
        if _is_ignored_path(path.relative_to(root)):
            continue
        if path not in selected:
            selected.append(path)

    source_candidates = sorted((root / "src").rglob("*.py")) if (root / "src").exists() else []
    for path in source_candidates:
        if len(selected) >= max_files:
            break
        rel = path.relative_to(root)
        if _is_ignored_path(rel):
            continue
        if path in selected:
            continue
        try:
            if path.stat().st_size > 8192:
                continue
        except Exception:
            continue
        selected.append(path)

    if len(selected) < max_files:
        for name in ("main.py", "cli.py", "app.py"):
            path = root / name
            if len(selected) >= max_files:
                break
            if path.exists() and path.is_file() and path not in selected:
                selected.append(path)

    files: list[dict[str, str]] = []
    for path in selected[:max_files]:
        rel = path.relative_to(root).as_posix()
        content = _read_context_file(path, max_chars_per_file=max_chars_per_file)
        if content.strip():
            files.append({"path": rel, "content": content})

    return {"files": files}


def _control_requested(cfg: Any, cwd: Path) -> bool:
    setting = cfg.aegis.control_enabled
    key_available = bool(resolve_key("AEGIS_API_KEY", cwd))
    if isinstance(setting, bool):
        return setting
    lowered = str(setting).strip().lower()
    if lowered == "auto":
        return key_available
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return key_available


def _key_usage_metadata(cwd: Path, cfg: Any) -> list[dict[str, Any]]:
    provider_key = str(cfg.providers.api_key_env or "OPENAI_API_KEY").strip() or "OPENAI_API_KEY"
    tracked = [
        ("AEGIS_API_KEY", "aegis_control"),
        (provider_key, f"provider_{str(cfg.providers.provider or 'unknown').strip().lower()}"),
    ]
    usage: list[dict[str, Any]] = []
    for name, purpose in tracked:
        resolved = resolve_key_source(name, cwd)
        usage.append(
            {
                "name": name,
                "source": resolved.get("source", "missing"),
                "used_for": purpose,
                "present": bool(resolved.get("present", False)),
            }
        )
    return usage


def _extract_context_paths(context: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    files = context.get("files", []) if isinstance(context, dict) else []
    if not isinstance(files, list):
        return paths
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if path:
            paths.append(path)
    return paths


def should_regenerate(validation: dict[str, Any], quality: dict[str, Any] | None, issues: list[str], task_type: str) -> bool:
    if not bool(validation.get("valid", False)):
        return True
    confidence = float((quality or {}).get("confidence", 0.0))
    if confidence < 0.70:
        return True
    if "unexpected_source_modification_for_test_task" in issues:
        return True
    if "unrelated_files" in issues:
        return True
    if task_type == "test_generation":
        for issue in issues:
            if issue == "unexpected_source_modification_for_test_task":
                return True
    return False


def _collect_regeneration_reasons(
    validation: dict[str, Any],
    quality: dict[str, Any] | None,
    issues: list[str],
    task_type: str,
) -> list[str]:
    reasons: list[str] = []
    if not bool(validation.get("valid", False)):
        reasons.append("invalid_diff")
    confidence = float((quality or {}).get("confidence", 0.0))
    if confidence < 0.70:
        reasons.append("low_quality")
    if "unrelated_files" in issues:
        reasons.append("unrelated_files")
    if task_type == "test_generation" and "unexpected_source_modification_for_test_task" in issues:
        reasons.append("test_source_modification")
    return reasons


def _aegis_corrective_control(
    *,
    task: str,
    task_type: str,
    issues: list[str],
    validation_errors: list[str],
    context_paths: list[str],
    base_url: str,
) -> dict[str, Any]:
    fallback = {
        "applied": False,
        "status": "not_available",
        "reason": "not_available",
        "error": None,
        "constraints": [],
        "context_mode": None,
        "allowed_targets": [],
        "guidance_signals": [],
    }
    try:
        from aegis import AegisClient  # type: ignore
    except Exception:
        fallback["status"] = "not_available"
        fallback["reason"] = "not_available"
        return fallback
    try:
        client = AegisClient(base_url=base_url)
        response = client.auto().step(
            step_name="patch_regeneration_correction",
            step_input={
                "task": task,
                "task_type": task_type,
                "issues": issues,
                "validation_errors": validation_errors,
                "context_files": context_paths,
            },
            symptoms=["low_patch_quality"],
            severity="medium",
            metadata={"task_type": task_type},
        )
        if not isinstance(response, dict):
            fallback["status"] = "no_guidance_returned"
            fallback["reason"] = "no_guidance_returned"
            return fallback
        constraints = response.get("constraints", [])
        allowed_targets = response.get("allowed_targets", [])
        guidance_signals = response.get("guidance_signals", [])
        has_guidance = bool(constraints) or bool(allowed_targets) or bool(guidance_signals) or bool(response.get("context_mode"))
        if not has_guidance:
            fallback["status"] = "no_guidance_returned"
            fallback["reason"] = "no_guidance_returned"
            return fallback
        return {
            "applied": True,
            "status": "applied",
            "reason": "applied",
            "error": None,
            "constraints": constraints if isinstance(constraints, list) else [],
            "context_mode": response.get("context_mode"),
            "allowed_targets": allowed_targets if isinstance(allowed_targets, list) else [],
            "guidance_signals": guidance_signals if isinstance(guidance_signals, list) else [],
        }
    except Exception as exc:
        fallback["status"] = "client_error"
        fallback["reason"] = "client_error"
        fallback["error"] = str(exc)
        return fallback


def _parse_unified_diff_files(diff_text: str) -> list[dict[str, Any]]:
    lines = str(diff_text or "").splitlines()
    files: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("diff --git "):
            tokens = line.split()
            if len(tokens) >= 4:
                current = {"old_path": tokens[2].removeprefix("a/"), "new_path": tokens[3].removeprefix("b/"), "hunks": []}
                files.append(current)
            else:
                current = None
            i += 1
            continue
        if current is None:
            i += 1
            continue
        if line.startswith("--- "):
            p = line[4:].strip()
            current["old_path"] = None if p == "/dev/null" else p.removeprefix("a/")
            i += 1
            continue
        if line.startswith("+++ "):
            p = line[4:].strip()
            current["new_path"] = None if p == "/dev/null" else p.removeprefix("b/")
            i += 1
            continue
        m = _HUNK_RE.match(line)
        if m:
            hunk: dict[str, Any] = {"old_start": int(m.group("old_start")), "lines": []}
            i += 1
            while i < len(lines):
                content = lines[i]
                if content.startswith("diff --git ") or _HUNK_RE.match(content):
                    break
                if content.startswith((" ", "+", "-")):
                    hunk["lines"].append((content[:1], content[1:]))
                i += 1
            current["hunks"].append(hunk)
            continue
        i += 1
    return files


def _apply_hunks_in_memory(source: str, hunks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    src = source.splitlines()
    out: list[str] = []
    src_idx = 0
    for hunk in hunks:
        start = int(hunk.get("old_start", 1))
        target_idx = 0 if start == 0 else start - 1
        if target_idx < src_idx or target_idx > len(src):
            return None, "context_mismatch"
        out.extend(src[src_idx:target_idx])
        src_idx = target_idx
        for kind, text in hunk.get("lines", []):
            if kind == " ":
                if src_idx >= len(src) or src[src_idx] != text:
                    return None, "context_mismatch"
                out.append(src[src_idx])
                src_idx += 1
            elif kind == "-":
                if src_idx >= len(src) or src[src_idx] != text:
                    return None, "context_mismatch"
                src_idx += 1
            elif kind == "+":
                out.append(text)
    out.extend(src[src_idx:])
    if not out:
        return "", None
    return "\n".join(out) + ("\n" if source.endswith("\n") or not source else ""), None


def _syntactic_python_check(diff_text: str, cwd: Path) -> tuple[bool, str | None]:
    files = _parse_unified_diff_files(diff_text)
    for f in files:
        new_path = f.get("new_path")
        old_path = f.get("old_path")
        target = new_path or old_path
        if not isinstance(target, str) or not target.endswith(".py"):
            continue
        path = cwd / target
        source = ""
        if old_path is not None and path.exists():
            source = path.read_text(encoding="utf-8")
        updated, apply_error = _apply_hunks_in_memory(source, f.get("hunks", []))
        if apply_error or updated is None:
            return False, f"{target}: {apply_error or 'syntax_precheck_failed'}"
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return False, f"{target}: {exc}"
    return True, None


def _refine_task_context_with_aegis(task: str, local_context: dict, cwd: Path, cfg: Any) -> dict:
    if not _control_requested(cfg, cwd):
        return local_context
    try:
        from aegis import AegisClient  # type: ignore
    except Exception:
        return local_context

    try:
        client = AegisClient(base_url=str(cfg.aegis.base_url))
        payload = client.auto().context(
            objective=task,
            messages=[
                {"role": "system", "content": "You are refining context for a code modification task."},
                {"role": "user", "content": json.dumps(local_context, ensure_ascii=True)},
            ],
            constraints=[
                "Preserve relevant files",
                "Remove noise",
                "Prioritize entrypoints and integration points",
            ],
            symptoms=["context_noise"],
            severity="medium",
            metadata={"task_type": "patch_generation"},
        )
        if isinstance(payload, dict):
            scope_data = payload.get("scope_data", {})
            if isinstance(scope_data, dict):
                cleaned = scope_data.get("cleaned_messages")
                if isinstance(cleaned, list):
                    for msg in cleaned:
                        if isinstance(msg, dict):
                            content = msg.get("content")
                            if isinstance(content, str):
                                try:
                                    parsed = json.loads(content)
                                except Exception:
                                    continue
                                if isinstance(parsed, dict) and isinstance(parsed.get("files"), list) and parsed.get("files"):
                                    return parsed
            cleaned_messages = payload.get("cleaned_messages")
            if isinstance(cleaned_messages, list):
                for msg in cleaned_messages:
                    if isinstance(msg, dict):
                        content = msg.get("content")
                        if isinstance(content, str):
                            try:
                                parsed = json.loads(content)
                            except Exception:
                                continue
                            if isinstance(parsed, dict) and isinstance(parsed.get("files"), list) and parsed.get("files"):
                                return parsed
    except Exception:
        return local_context
    return local_context


def build_run_payload(
    *,
    options: TaskOptions,
    cwd: Path | None = None,
    client: AegisBackendClient | None = None,
) -> dict[str, Any]:
    config = load_config(cwd)
    apply_resolved_aegis_env((cwd or Path.cwd()).resolve(), default_base_url=config.aegis.base_url)
    guidance = options.aegis_guidance or {}
    guidance_tier = str(guidance.get("model_tier", "") or "").strip().lower()
    guidance_max_retries_raw = guidance.get("max_retries")
    guidance_allow_escalation = guidance.get("allow_escalation")
    guidance_context_mode = str(guidance.get("context_mode", "") or "").strip().lower() or None

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

            effective_max_retries = int(decision.max_retries)
            if isinstance(guidance_max_retries_raw, int):
                effective_max_retries = min(effective_max_retries, max(0, guidance_max_retries_raw))
            effective_allow_escalation = bool(decision.allow_escalation)
            if guidance_allow_escalation is False:
                effective_allow_escalation = False
            decision.max_retries = effective_max_retries
            decision.allow_escalation = effective_allow_escalation

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
            if final_passed and retry_policy["retry_count"] > 0:
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

    if isinstance(guidance_max_retries_raw, int):
        decision.max_retries = min(int(decision.max_retries), max(0, guidance_max_retries_raw))
    if guidance_allow_escalation is False:
        decision.allow_escalation = False

    if guidance_tier in {"cheap", "mid", "premium"}:
        decision.model_tier = guidance_tier
    elif str(mode).strip().lower() == "cheapest":
        decision.model_tier = "cheap"
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
    final_failure_count = int(final_failures.get("failure_count", 0) or 0)
    task_driven_patch_proposal = bool(options.propose_patch and final_failure_count == 0 and is_constructive_task(options.task))
    should_patch_flow = bool(final_failure_count > 0 or task_driven_patch_proposal)
    if task_driven_patch_proposal:
        local_task_context = build_task_context((cwd or Path.cwd()).resolve())
        refined_task_context = _refine_task_context_with_aegis(
            options.task,
            local_task_context,
            (cwd or Path.cwd()).resolve(),
            config,
        )
        final_task_context = refined_task_context if isinstance(refined_task_context, dict) else local_task_context
        files = final_task_context.get("files") if isinstance(final_task_context, dict) else None
        if not isinstance(files, list) or not files:
            final_task_context = local_task_context
        failure_context = final_task_context

        entrypoint_file = ""
        for item in failure_context.get("files", []) if isinstance(failure_context, dict) else []:
            if isinstance(item, dict):
                path = str(item.get("path", ""))
                if path in {"src/main.py", "main.py", "cli.py", "app.py"}:
                    entrypoint_file = path
                    break
        test_task = is_test_generation_task(options.task)
        patch_plan = {
            "strategy": f"Implement requested task: {options.task}. Keep changes minimal and localized.",
            "confidence": 0.5,
            "proposed_changes": [
                {
                    "file": "",
                    "change_type": "task_intent",
                    "description": "Patch proposal generated from task intent (no test failures).",
                    "reason": "constructive_task_intent",
                }
            ],
        }
        if test_task:
            test_file_hint = _test_hint_path(options.task, failure_context)
            patch_plan["task_type"] = "test_generation"
            patch_plan["target_file"] = test_file_hint
            patch_plan["strategy"] += (
                " Prefer modifying tests only. Avoid source changes unless explicitly requested. "
                "Place imports at the top of test files, replace placeholder tests cleanly, and keep hunk counts valid."
            )
            patch_plan["proposed_changes"].append(
                {
                    "file": test_file_hint,
                    "change_type": "modify" if test_file_hint.startswith("tests/") and any(
                        isinstance(item, dict) and str(item.get("path", "")).strip() == test_file_hint
                        for item in failure_context.get("files", [])
                    ) else "create",
                    "description": "Add tests for requested behavior.",
                    "reason": "test_generation_task",
                }
            )
        if entrypoint_file and not test_task:
            patch_plan["proposed_changes"].append(
                {
                    "file": entrypoint_file,
                    "change_type": "modify",
                    "description": "Integrate feature into CLI entrypoint.",
                    "reason": "entrypoint_integration",
                }
            )

    provider_enabled = bool(config.providers.enabled or options.propose_patch)
    has_context_files = bool(failure_context.get("files", []))
    has_proposed_changes = bool(patch_plan.get("proposed_changes", []))

    if (
        should_attempt_provider_diff
        and provider_enabled
        and verification.get("available", False)
        and should_patch_flow
        and (has_context_files or has_proposed_changes)
    ):
        task_type = str(patch_plan.get("task_type", "general") or "general")
        test_task = task_type == "test_generation" or is_test_generation_task(options.task)
        regeneration: dict[str, Any] = {
            "triggered": False,
            "reason": "none",
            "reasons": [],
            "attempted": False,
            "aegis_guidance_applied": False,
            "final_status": "not_needed",
            "corrective_control_status": "not_triggered",
            "corrective_control_reason": "not_triggered",
            "corrective_control_error": None,
        }
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
        initial_diff = normalize_unified_diff(str(provider_result.get("diff", "") or "").strip()).strip()
        validation_result = inspect_diff(initial_diff, cwd=(cwd or Path.cwd())) if initial_diff else {"valid": False, "errors": ["empty_diff"]}
        repair_result = {
            "applied": False,
            "status": "skipped",
            "reason": "not_attempted",
            "diff": initial_diff,
            "error": None,
        }
        repair_attempted = False
        if initial_diff and not bool(validation_result.get("valid", False)):
            repair_attempted = True
            repair_result = repair_malformed_diff(
                initial_diff,
                cwd=(cwd or Path.cwd()),
                task=options.task,
                patch_plan=patch_plan,
                context=failure_context,
            )
            if bool(repair_result.get("applied", False)):
                initial_diff = str(repair_result.get("diff", "") or initial_diff)
                validation_result = inspect_diff(initial_diff, cwd=(cwd or Path.cwd()))
        initial_quality = evaluate_diff(
            initial_diff,
            final_failures,
            failure_context,
            test_generation_task=test_task,
        ) if initial_diff else {
            "grounded": False,
            "relevant_files": False,
            "confidence": 0.0,
            "issues": ["empty_diff"],
        }
        initial_issues = [str(item) for item in initial_quality.get("issues", [])]
        regenerate = should_regenerate(validation_result, initial_quality, initial_issues, task_type)
        reasons = _collect_regeneration_reasons(validation_result, initial_quality, initial_issues, task_type)
        regeneration["triggered"] = regenerate
        regeneration["reasons"] = reasons
        if reasons:
            regeneration["reason"] = reasons[0]

        provider_used = provider_result
        diff_text = initial_diff
        quality_used = initial_quality
        validation_used = validation_result

        if regenerate:
            regeneration["attempted"] = True
            enhanced_patch_plan = deepcopy(patch_plan)
            enhanced_constraints = [
                "Produce a valid unified diff.",
                "Ensure hunk line counts match unified diff headers.",
                "Minimize unrelated file changes.",
            ]
            if test_task:
                enhanced_constraints.extend(
                    [
                        "Modify only tests/ paths unless explicitly requested.",
                        "Keep imports at top of test files.",
                        "Replace placeholder tests cleanly; do not append imports after test functions.",
                    ]
                )
                enhanced_patch_plan["allowed_targets"] = [
                    path for path in _extract_context_paths(failure_context) if path.startswith("tests/")
                ]
            if _control_requested(config, (cwd or Path.cwd()).resolve()):
                corrective = _aegis_corrective_control(
                    task=options.task,
                    task_type=task_type,
                    issues=initial_issues,
                    validation_errors=[str(item) for item in validation_result.get("errors", [])],
                    context_paths=_extract_context_paths(failure_context),
                    base_url=str(config.aegis.base_url),
                )
                regeneration["corrective_control_status"] = str(corrective.get("status", "client_error"))
                regeneration["corrective_control_reason"] = str(corrective.get("reason", "client_error"))
                regeneration["corrective_control_error"] = corrective.get("error")
                if corrective.get("applied", False):
                    regeneration["aegis_guidance_applied"] = True
                    if isinstance(corrective.get("constraints"), list):
                        enhanced_constraints.extend(str(item) for item in corrective.get("constraints", []))
                    if isinstance(corrective.get("allowed_targets"), list) and corrective.get("allowed_targets"):
                        enhanced_patch_plan["allowed_targets"] = [
                            str(item) for item in corrective.get("allowed_targets", [])
                        ]
                    if corrective.get("context_mode"):
                        enhanced_patch_plan["context_mode"] = str(corrective.get("context_mode"))
                    if isinstance(corrective.get("guidance_signals"), list) and corrective.get("guidance_signals"):
                        enhanced_patch_plan["guidance_signals"] = [
                            str(item) for item in corrective.get("guidance_signals", [])
                        ]
            else:
                regeneration["corrective_control_status"] = "disabled_by_config"
                regeneration["corrective_control_reason"] = "disabled_by_config"
            enhanced_patch_plan["regeneration_constraints"] = sorted(set(enhanced_constraints))

            second = generate_patch_diff(
                provider=config.providers.provider,
                model=selected_model,
                task=options.task,
                failures=final_failures,
                context=failure_context,
                patch_plan=enhanced_patch_plan,
                aegis_execution=decision.execution if isinstance(decision.execution, dict) else {},
                api_key_env=config.providers.api_key_env,
                max_context_chars=int(config.patches.max_context_chars),
            )
            second_diff = normalize_unified_diff(str(second.get("diff", "") or "").strip()).strip()
            second_validation = inspect_diff(second_diff, cwd=(cwd or Path.cwd())) if second_diff else {"valid": False, "errors": ["empty_diff"]}
            second_quality = evaluate_diff(
                second_diff,
                final_failures,
                failure_context,
                test_generation_task=test_task,
            ) if second_diff else {
                "grounded": False,
                "relevant_files": False,
                "confidence": 0.0,
                "issues": ["empty_diff"],
            }
            provider_used = second
            diff_text = second_diff
            validation_used = second_validation
            quality_used = second_quality

        path_value: str | None = None
        invalid_path: str | None = None
        if provider_used.get("available", False) and diff_text and bool(validation_used.get("valid", False)):
            syntactic_valid, syntactic_error = _syntactic_python_check(diff_text, cwd=(cwd or Path.cwd()))
            diff_path = write_latest_diff(diff_text, cwd=cwd)
            remove_latest_invalid_diff(cwd=cwd)
            path_value = str(diff_path)
            patch_quality = quality_used
        else:
            patch_quality = None
            syntactic_valid, syntactic_error = None, None
            if provider_used.get("available", False) and diff_text:
                invalid_path = str(write_latest_invalid_diff(diff_text, cwd=cwd))
                remove_latest_diff(cwd=cwd)

        if path_value:
            final_status = "generated"
        elif not bool(provider_used.get("available", False)):
            final_status = "unavailable"
        else:
            final_status = "invalid"
        regeneration["final_status"] = final_status
        patch_diff = {
            "attempted": True,
            "available": bool(provider_used.get("available", False)) and bool(path_value),
            "status": final_status,
            "regenerated": bool(regenerate),
            "regeneration_attempted": bool(regeneration.get("attempted", False)),
            "aegis_corrective_control_applied": bool(regeneration.get("aegis_guidance_applied", False)),
            "repair_attempted": bool(repair_attempted),
            "repair_applied": bool(repair_result.get("applied", False)),
            "repair_status": str(repair_result.get("status", "skipped")),
            "repair_reason": str(repair_result.get("reason", "unknown")),
            "repair_error": repair_result.get("error"),
            "syntactic_valid": syntactic_valid,
            "syntactic_error": syntactic_error,
            "corrective_control_status": str(regeneration.get("corrective_control_status", "not_triggered")),
            "corrective_control_reason": str(regeneration.get("corrective_control_reason", "not_triggered")),
            "corrective_control_error": regeneration.get("corrective_control_error"),
            "regeneration": regeneration,
            "initial_diff": initial_diff[:800],
            "validation_result": validation_used,
            "validation_errors": [str(item) for item in validation_used.get("errors", [])],
            "quality_score": float((quality_used or {}).get("confidence", 0.0)),
            "issues": list((quality_used or {}).get("issues", [])),
            "provider": provider_used.get("provider"),
            "model": provider_used.get("model"),
            "path": path_value,
            "invalid_diff_path": invalid_path,
            "error": provider_used.get("error"),
            "preview": diff_text[:800],
        }
        if provider_used.get("available", False) and not path_value:
            patch_diff["available"] = False
            validation_errors = validation_used.get("errors", [])
            if validation_errors:
                patch_diff["error"] = str(validation_errors[0])
            else:
                patch_diff["error"] = "Diff generation returned empty output."
        if patch_diff["attempted"] and not patch_diff["available"] and not patch_diff.get("error"):
            patch_diff["error"] = "Provider unavailable"
    elif should_attempt_provider_diff and not provider_enabled:
        patch_diff = {
            "attempted": True,
            "available": False,
            "status": "unavailable",
            "regenerated": False,
            "regeneration_attempted": False,
            "aegis_corrective_control_applied": False,
            "corrective_control_status": "not_triggered",
            "corrective_control_reason": "not_triggered",
            "corrective_control_error": None,
            "provider": config.providers.provider,
            "model": selected_model,
            "path": None,
            "error": "Provider unavailable",
            "preview": "",
        }
    elif should_attempt_provider_diff and should_patch_flow and not verification.get("available", False):
        patch_diff = {
            "attempted": True,
            "available": False,
            "status": "unavailable",
            "regenerated": False,
            "regeneration_attempted": False,
            "aegis_corrective_control_applied": False,
            "corrective_control_status": "not_triggered",
            "corrective_control_reason": "not_triggered",
            "corrective_control_error": None,
            "provider": config.providers.provider,
            "model": selected_model,
            "path": None,
            "error": "Provider unavailable",
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
            "available_project_keys": sorted(list(list_scoped_keys((cwd or Path.cwd()).resolve()).get("project", {}).keys())),
            "available_global_keys": sorted(list(list_scoped_keys((cwd or Path.cwd()).resolve()).get("global", {}).keys())),
            "secret_values_exposed": False,
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
        "applied_aegis_guidance": {
            "model_tier_override": guidance_tier if guidance_tier in {"cheap", "mid", "premium"} else None,
            "max_retries_applied": int(decision.max_retries),
            "escalation_allowed": bool(decision.allow_escalation),
            "context_mode": guidance_context_mode or "balanced",
        },
        "task_driven_patch_proposal": task_driven_patch_proposal,
        "key_usage": _key_usage_metadata((cwd or Path.cwd()).resolve(), config),
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
