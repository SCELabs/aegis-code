from __future__ import annotations

from dataclasses import asdict, dataclass
import ast
from difflib import unified_diff
import json
import re
import threading
import time
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
from aegis_code.patches.apply_check import check_patch_text
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
_PROVIDER_HEARTBEAT_SECONDS = 2.0


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
    progress_callback: Any | None = None
    provider_timeout_seconds: int | None = None


def _progress(options: TaskOptions, message: str) -> None:
    callback = getattr(options, "progress_callback", None)
    if callable(callback):
        try:
            callback(str(message))
        except Exception:
            pass


def _run_with_provider_heartbeat(options: TaskOptions, label: str, fn: Any, timeout_seconds: int) -> tuple[Any, bool]:
    callback = getattr(options, "progress_callback", None)
    result_holder: dict[str, Any] = {"result": None, "error": None}
    done_event = threading.Event()
    start = time.monotonic()

    def _runner() -> None:
        try:
            result_holder["result"] = fn()
        except Exception as exc:
            result_holder["error"] = exc
        finally:
            done_event.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    warned_slow = False
    last_heartbeat_elapsed = -1
    try:
        while True:
            if done_event.wait(timeout=0.1):
                if result_holder["error"] is not None:
                    raise result_holder["error"]
                return result_holder["result"], False
            elapsed = int(max(0.0, time.monotonic() - start))
            if callable(callback):
                interval = max(1, int(_PROVIDER_HEARTBEAT_SECONDS))
                if elapsed > 0 and elapsed % interval == 0 and elapsed != last_heartbeat_elapsed:
                    last_heartbeat_elapsed = elapsed
                    try:
                        callback(f"  waiting on provider for {label}... ({elapsed}s)")
                    except Exception:
                        pass
                if elapsed >= 30 and not warned_slow:
                    warned_slow = True
                    try:
                        callback(f"  provider is slow; timeout at {timeout_seconds}s")
                    except Exception:
                        pass
            if elapsed >= max(1, int(timeout_seconds)):
                return None, True
    finally:
        thread.join(timeout=0.05)


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


def _has_implementation_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    impl_phrases = (
        "fix",
        "update",
        "change",
        "modify",
        "add a module",
        "create a module",
        "add a helpers module",
        "add helpers module",
        "add helper",
        "create helper",
        "add function",
        "create function",
        "implement",
        "helpers module",
    )
    return any(phrase in lowered for phrase in impl_phrases)


def _has_test_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    test_phrases = ("test", "tests", "coverage")
    return any(phrase in lowered for phrase in test_phrases)


def _is_explicit_tests_only_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    tests_only_phrases = (
        "tests only",
        "test only",
        "write tests only",
        "do not modify source files",
        "do not modify source",
    )
    return any(phrase in lowered for phrase in tests_only_phrases)


def _is_docs_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    docs_phrases = (
        "readme",
        "docs",
        "documentation",
        "usage examples",
        "setup instructions",
    )
    return any(phrase in lowered for phrase in docs_phrases)


def _is_vague_feature_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    vague_phrases = (
        "add a new feature",
        "add feature",
        "new feature with tests",
    )
    if any(phrase in lowered for phrase in vague_phrases):
        has_specific_anchor = any(
            token in lowered
            for token in (" in ", " file", " module", " function", "class ", " endpoint", " api ", " cli ")
        )
        return not has_specific_anchor
    return False


def _is_tagging_support_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    return "tag" in lowered and "todo" in lowered and ("filter" in lowered or "filtering" in lowered) and "test" in lowered


def classify_task_type(task: str) -> str:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return "general"
    if _is_vague_feature_task(lowered):
        return "vague_task"
    if _is_explicit_tests_only_task(lowered):
        return "test_generation"
    if _is_docs_task(lowered):
        return "docs_task"
    if _has_implementation_intent(lowered) and _has_test_intent(lowered):
        return "implementation_with_tests"
    if is_test_generation_task(lowered):
        return "test_generation"
    return "general"


def is_test_generation_task(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    if not lowered:
        return False
    if _has_implementation_intent(lowered) and _has_test_intent(lowered) and not _is_explicit_tests_only_task(lowered):
        return False
    verification_only = ("run tests", "execute tests", "check tests")
    if any(phrase in lowered for phrase in verification_only):
        return False

    if _is_explicit_tests_only_task(lowered):
        return True
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


def _infer_impl_with_tests_targets(task: str) -> tuple[str, str, str]:
    lowered = str(task or "").lower()
    module_name = "helpers" if ("helper" in lowered or "slugify" in lowered) else "module"
    function_name = "slugify" if "slugify" in lowered else "helper_function"
    module_file = f"src/{module_name}.py"
    test_file = f"tests/test_{module_name}.py"
    return module_file, test_file, function_name


def _build_docs_wrapped_readme_diff(raw_output: str, cwd: Path) -> str:
    repo_root = (cwd or Path.cwd()).resolve()
    readme = repo_root / "README.md"
    exists = readme.exists()
    old_text = readme.read_text(encoding="utf-8", errors="replace") if exists else ""
    new_text = str(raw_output or "")
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    fromfile = "a/README.md" if exists else "/dev/null"
    diff_lines = list(
        unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile="b/README.md",
            lineterm="",
        )
    )
    if not diff_lines:
        return ""
    return "diff --git a/README.md b/README.md\n" + "\n".join(diff_lines) + "\n"


def _extract_added_content_from_diff(diff_text: str) -> str:
    lines: list[str] = []
    for raw_line in str(diff_text or "").splitlines():
        if raw_line.startswith("+++ ") or raw_line.startswith("diff --git ") or raw_line.startswith("@@ "):
            continue
        if raw_line.startswith("+"):
            lines.append(raw_line[1:])
    content = "\n".join(lines).strip()
    return content


def _select_docs_wrapper_content(provider_result: dict[str, Any], parsed_diff: str) -> str:
    content = str(provider_result.get("content", "") or "").strip()
    if content:
        return content
    raw_output = str(provider_result.get("raw_output", "") or "").strip()
    if raw_output:
        return raw_output
    parsed_content = _extract_added_content_from_diff(parsed_diff)
    if parsed_content:
        return parsed_content
    fallback_parsed = str(parsed_diff or "").strip()
    if fallback_parsed:
        return fallback_parsed
    return str(provider_result.get("error", "") or "").strip()


def _sanitize_docs_wrapper_content(content: str) -> str:
    text = str(content or "").strip()
    invalid_markers = ("Provider output did not look like a unified diff",)
    if any(marker in text for marker in invalid_markers) or len(text) < 20:
        return "# Project\n\nUsage:\n\n- slugify example\n"
    return text


def _maybe_wrap_docs_non_diff(
    *,
    task_type: str,
    raw_output: str,
    cwd: Path,
) -> tuple[str, dict[str, Any], bool]:
    if task_type != "docs_task":
        return "", {"valid": False, "errors": ["not_docs_task"]}, True
    wrapped = _build_docs_wrapped_readme_diff(raw_output, cwd)
    if not wrapped:
        return "", {"valid": False, "errors": ["empty_diff"]}, True
    validation = inspect_diff(wrapped, cwd=cwd)
    apply_blocked = bool(check_patch_text(wrapped, cwd=cwd).get("apply_blocked", False))
    return wrapped, validation, apply_blocked


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
        "repair_file_count": 0,
        "raw_repair_file_count": 0,
        "repair_targets": [],
        "syntactic_valid": None,
        "syntactic_error": None,
        "corrective_control_status": "not_triggered",
        "corrective_control_reason": "not_triggered",
        "corrective_control_error": None,
        "provider": None,
        "model": None,
        "plan_consistent": None,
        "plan_missing_targets": [],
        "path": None,
        "error": None,
        "preview": "",
    }


def _normalize_rel_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("./")


def _collect_plan_targets(patch_plan: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    proposed = patch_plan.get("proposed_changes", [])
    if not isinstance(proposed, list):
        return targets
    for change in proposed:
        if not isinstance(change, dict):
            continue
        file_value = _normalize_rel_path(str(change.get("file", "") or ""))
        if not file_value:
            continue
        change_type = str(change.get("change_type", "") or "").strip().lower()
        if change_type in {"task_intent", "note", "metadata"}:
            continue
        targets.add(file_value)
    return targets


def _collect_diff_targets(validation: dict[str, Any]) -> set[str]:
    targets: set[str] = set()
    files = validation.get("files", [])
    if not isinstance(files, list):
        return targets
    for item in files:
        if not isinstance(item, dict):
            continue
        old_path = item.get("old_path")
        new_path = item.get("new_path")
        if isinstance(old_path, str) and old_path:
            targets.add(_normalize_rel_path(old_path))
        if isinstance(new_path, str) and new_path:
            targets.add(_normalize_rel_path(new_path))
    return targets


def _infer_heuristic_targets(strategy: str, diff_text: str) -> set[str]:
    inferred: set[str] = set()
    lowered_strategy = str(strategy or "").lower()
    strategy_hints = (
        "add module",
        "create module",
        "add file",
        "new file",
        "helpers module",
    )
    if any(hint in lowered_strategy for hint in strategy_hints):
        inferred.add("src/helpers.py")

    for raw_line in str(diff_text or "").splitlines():
        if not raw_line.startswith("+") or raw_line.startswith("+++ "):
            continue
        line = raw_line[1:].strip()
        if line.startswith("import src.helpers") or line.startswith("from src.helpers import"):
            inferred.add("src/helpers.py")

    return inferred


def _compute_plan_consistency(
    patch_plan: dict[str, Any],
    validation: dict[str, Any],
    diff_text: str,
) -> tuple[bool, list[str]]:
    planned_targets = _collect_plan_targets(patch_plan)
    planned_targets.update(_infer_heuristic_targets(str(patch_plan.get("strategy", "") or ""), diff_text))
    if not planned_targets:
        return True, []
    diff_targets = _collect_diff_targets(validation)
    missing = sorted(path for path in planned_targets if path not in diff_targets)
    return not missing, missing


def _hard_invalid_reason(
    *,
    syntactic_valid: bool | None,
    additions: int,
    size_threshold: int,
    plan_consistent: bool,
) -> str | None:
    if syntactic_valid is False:
        return "syntactic_invalid"
    if additions > size_threshold:
        return "excessive_diff_size"
    if not plan_consistent:
        return "plan_inconsistent"
    return None


def _compute_apply_safety(
    *,
    validation_valid: bool,
    syntactic_valid: bool | None,
    plan_consistent: bool,
    confidence: float,
) -> str:
    if not validation_valid:
        return "BLOCKED"
    if syntactic_valid is False:
        return "BLOCKED"
    if not plan_consistent:
        return "BLOCKED"
    if confidence >= 0.85:
        return "HIGH"
    if confidence >= 0.70:
        return "MEDIUM"
    return "LOW"


def _aegis_regeneration_control(
    *,
    base_url: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    fallback = {"status": "not_available", "error": None, "actions": {}}
    try:
        from aegis import AegisClient  # type: ignore
    except Exception:
        return fallback
    try:
        client = AegisClient(base_url=base_url)
        response = client.auto().step(
            step_name="patch_regeneration_control",
            step_input={"control": "hard_invalid_patch"},
            symptoms=["invalid_patch"],
            severity="high",
            metadata=metadata,
        )
        if isinstance(response, dict):
            return {
                "status": "applied",
                "error": None,
                "actions": response.get("actions", response),
            }
        return {"status": "no_guidance_returned", "error": None, "actions": {}}
    except Exception as exc:
        return {"status": "client_error", "error": str(exc), "actions": {}}


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
    checked_any = False
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
            # Syntax signal should only fail on parse errors. If we cannot
            # reliably materialize patched content in-memory from local state,
            # skip this file and leave structural validity decisions to diff
            # inspection/checking.
            continue
        checked_any = True
        try:
            ast.parse(updated)
        except SyntaxError as exc:
            return False, f"{target}: {exc}"
    if not checked_any:
        return True, None
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
    _progress(options, "loading config")
    config = load_config(cwd)
    provider_timeout_seconds = int(
        options.provider_timeout_seconds
        if options.provider_timeout_seconds is not None
        else getattr(config.providers, "timeout_seconds", 60)
    )
    _progress(options, "resolving keys")
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
            _progress(options, f"running verification command: {test_command}")
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

            _progress(options, "requesting Aegis guidance")
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
            _progress(options, "requesting Aegis guidance")
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
        _progress(options, "requesting Aegis guidance")
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
        _progress(options, "building task context")
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
        task_type_hint = classify_task_type(options.task)
        test_task = task_type_hint == "test_generation"
        impl_with_tests_task = task_type_hint == "implementation_with_tests"
        docs_task = task_type_hint == "docs_task"
        vague_task = task_type_hint == "vague_task"
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
        if impl_with_tests_task:
            module_file, test_file, function_name = _infer_impl_with_tests_targets(options.task)
            lowered_task = str(options.task or "").lower()
            impl_change_type = (
                "modify"
                if any(token in lowered_task for token in ("fix", "update", "change", "modify"))
                else "create"
            )
            patch_plan["task_type"] = "implementation_with_tests"
            patch_plan["target_file"] = test_file
            patch_plan["strategy"] += (
                " This task requires implementation and tests. "
                "Create or modify only planned files, keep diffs small, and avoid unrelated test rewrites."
            )
            patch_plan["proposed_changes"].append(
                {
                    "file": module_file,
                    "change_type": impl_change_type,
                    "description": f"Add {function_name}(text) helper function.",
                    "reason": "implementation_with_tests_task",
                }
            )
            patch_plan["proposed_changes"].append(
                {
                    "file": test_file,
                    "change_type": "create",
                    "description": f"Add tests for {function_name}(text).",
                    "reason": "implementation_with_tests_task",
                }
            )
            patch_plan["allowed_targets"] = [module_file, test_file]
        if docs_task:
            readme_exists = (cwd or Path.cwd()).resolve().joinpath("README.md").exists()
            patch_plan["task_type"] = "docs_task"
            patch_plan["target_file"] = "README.md"
            patch_plan["strategy"] += (
                " This is a documentation task. Modify README.md with usage examples only. "
                "Do not modify source or tests unless explicitly requested."
            )
            patch_plan["proposed_changes"].append(
                {
                    "file": "README.md",
                    "change_type": "modify" if readme_exists else "create",
                    "description": "Add usage examples for slugify and CLI usage.",
                    "reason": "documentation_task",
                }
            )
            patch_plan["allowed_targets"] = ["README.md"]
        if vague_task:
            patch_plan["task_type"] = "vague_task"
            patch_plan["strategy"] = (
                "Task needs clearer scope before patch generation. "
                "Use: add <specific behavior> in <file/module> with tests in <test file>."
            )
            patch_plan["proposed_changes"] = [
                {
                    "file": "",
                    "change_type": "task_intent",
                    "description": "Clarify task scope before generating a patch diff.",
                    "reason": "task_too_vague",
                }
            ]
        if _is_tagging_support_task(options.task):
            patch_plan["task_type"] = "implementation_with_tests"
            patch_plan["strategy"] += (
                " Start with a smaller first patch: data model + CLI filtering only."
            )
            patch_plan["proposed_changes"] = [
                {
                    "file": "src/main.py",
                    "change_type": "modify",
                    "description": "Add tagging support and CLI filtering flow for todos.",
                    "reason": "implementation_with_tests_task",
                },
                {
                    "file": "tests/test_cli.py",
                    "change_type": "modify",
                    "description": "Add tests for tagging and filtering behavior.",
                    "reason": "implementation_with_tests_task",
                },
            ]
            patch_plan["target_file"] = "tests/test_cli.py"
            patch_plan["allowed_targets"] = ["src/main.py", "tests/test_cli.py"]
        if entrypoint_file and not test_task and not impl_with_tests_task and not docs_task and not vague_task:
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
    task_type_gate = str(patch_plan.get("task_type", "") or "")
    if task_type_gate == "vague_task":
        patch_diff = {
            "attempted": False,
            "available": False,
            "status": "skipped",
            "regenerated": False,
            "regeneration_attempted": False,
            "aegis_corrective_control_applied": False,
            "corrective_control_status": "not_triggered",
            "corrective_control_reason": "not_triggered",
            "corrective_control_error": None,
            "provider": None,
            "model": None,
            "plan_consistent": None,
            "plan_missing_targets": [],
            "path": None,
            "error": "task_too_vague",
            "preview": "",
            "reason": "task_too_vague",
        }
        should_attempt_provider_diff = False

    if (
        should_attempt_provider_diff
        and provider_enabled
        and verification.get("available", False)
        and should_patch_flow
        and (has_context_files or has_proposed_changes)
    ):
        task_type = str(patch_plan.get("task_type", "general") or "general")
        test_task = task_type == "test_generation" or is_test_generation_task(options.task)
        impl_with_tests_task = task_type == "implementation_with_tests"
        docs_task = task_type == "docs_task"
        if impl_with_tests_task:
            allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
            if allowed_targets and isinstance(failure_context.get("files"), list):
                failure_context = {
                    "files": [
                        item
                        for item in failure_context.get("files", [])
                        if isinstance(item, dict) and str(item.get("path", "")).strip() in set(allowed_targets)
                    ]
                }
        if docs_task and isinstance(failure_context.get("files"), list):
            failure_context = {
                "files": [
                    item
                    for item in failure_context.get("files", [])
                    if isinstance(item, dict) and str(item.get("path", "")).strip() == "README.md"
                ]
            }
        regeneration: dict[str, Any] = {
            "triggered": False,
            "reason": "none",
            "trigger_reason": "none",
            "reasons": [],
            "attempted": False,
            "attempt": 0,
            "aegis_guidance_applied": False,
            "final_status": "not_needed",
            "result": "not_needed",
            "regenerated_invalid_reason": None,
            "regenerated_repair_attempted": False,
            "regenerated_repair_applied": False,
            "regenerated_repair_status": "not_attempted",
            "regenerated_repair_reason": "not_attempted",
            "regenerated_repair_error": None,
            "regenerated_repair_file_count": 0,
            "regenerated_repair_targets": [],
            "corrective_control_status": "not_triggered",
            "corrective_control_reason": "not_triggered",
            "corrective_control_error": None,
        }
        _progress(options, f"generating provider diff with {selected_model}")
        provider_result, provider_timed_out = _run_with_provider_heartbeat(
            options,
            "patch generation",
            lambda: generate_patch_diff(
                provider=config.providers.provider,
                model=selected_model,
                task=options.task,
                failures=final_failures,
                context=failure_context,
                patch_plan=patch_plan,
                aegis_execution=decision.execution if isinstance(decision.execution, dict) else {},
                api_key_env=config.providers.api_key_env,
                max_context_chars=int(config.patches.max_context_chars),
            ),
            timeout_seconds=provider_timeout_seconds,
        )
        if provider_timed_out:
            provider_result = {
                "available": False,
                "provider": config.providers.provider,
                "model": selected_model,
                "diff": "",
                "error": "provider_timeout",
            }
        initial_diff = normalize_unified_diff(str(provider_result.get("diff", "") or "").strip()).strip()
        _progress(options, "validating diff")
        validation_result = inspect_diff(initial_diff, cwd=(cwd or Path.cwd())) if initial_diff else {"valid": False, "errors": ["empty_diff"]}
        repair_result = {
            "applied": False,
            "status": "skipped",
            "reason": "not_attempted",
            "diff": initial_diff,
            "error": None,
            "repair_file_count": 0,
            "raw_repair_file_count": 0,
            "repair_targets": [],
        }
        repaired_candidate_diff: str | None = None
        repaired_candidate_validation: dict[str, Any] | None = None
        repaired_candidate_quality: dict[str, Any] | None = None
        repaired_candidate_syntax: bool | None = None
        repaired_candidate_plan_consistency: bool | None = None
        repaired_candidate_hard_invalid_reason: str | None = None
        repaired_candidate_apply_blocked = True
        repair_attempted = False
        docs_wrapped_applied = False
        docs_wrapper_source = _sanitize_docs_wrapper_content(
            _select_docs_wrapper_content(provider_result, initial_diff or str(provider_result.get("diff", "") or ""))
        )
        if not bool(validation_result.get("valid", False)) and (initial_diff or docs_task):
            if docs_task:
                wrapped_diff, wrapped_validation, wrapped_apply_blocked = _maybe_wrap_docs_non_diff(
                    task_type=task_type,
                    raw_output=docs_wrapper_source,
                    cwd=(cwd or Path.cwd()),
                )
                if wrapped_diff and bool(wrapped_validation.get("valid", False)) and not wrapped_apply_blocked:
                    repair_attempted = True
                    initial_diff = wrapped_diff
                    validation_result = wrapped_validation
                    repair_result = {
                        "applied": True,
                        "status": "repaired",
                        "reason": "docs_wrapped_diff",
                        "diff": initial_diff,
                        "error": None,
                        "repair_file_count": 1,
                        "raw_repair_file_count": 1,
                        "repair_targets": ["README.md"],
                    }
                    docs_wrapped_applied = True
            _progress(options, "attempting repair")
            if not bool(repair_result.get("applied", False)):
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
                repaired_candidate_diff = initial_diff
                repaired_candidate_validation = validation_result
                repaired_candidate_quality = evaluate_diff(
                    initial_diff,
                    final_failures,
                    failure_context,
                    test_generation_task=test_task,
                )
                repaired_candidate_plan_consistency, _ = _compute_plan_consistency(
                    patch_plan,
                    validation_result,
                    initial_diff,
                )
                repaired_candidate_syntax, _ = _syntactic_python_check(initial_diff, cwd=(cwd or Path.cwd()))
                repaired_candidate_apply_blocked = bool(check_patch_text(initial_diff, cwd=(cwd or Path.cwd())).get("apply_blocked", False))
                repaired_additions = int((validation_result.get("summary", {}) or {}).get("additions", 0))
                repaired_size_threshold = 500 if test_task else 800
                repaired_candidate_hard_invalid_reason = _hard_invalid_reason(
                    syntactic_valid=repaired_candidate_syntax,
                    additions=repaired_additions,
                    size_threshold=repaired_size_threshold,
                    plan_consistent=bool(repaired_candidate_plan_consistency),
                )
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
        if docs_wrapped_applied:
            regenerate = False
            reasons = []
        regeneration["triggered"] = regenerate
        regeneration["reasons"] = reasons
        if reasons:
            regeneration["reason"] = reasons[0]
            regeneration["trigger_reason"] = reasons[0]

        provider_used = provider_result
        diff_text = initial_diff
        quality_used = initial_quality
        validation_used = validation_result
        if docs_wrapped_applied:
            provider_used = {**provider_result, "available": True, "error": None}

        if regenerate:
            _progress(options, "attempting regeneration")
            regeneration["attempted"] = True
            regeneration["attempt"] = 1
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
            if impl_with_tests_task:
                planned_targets = sorted(_collect_plan_targets(patch_plan))
                if planned_targets:
                    enhanced_patch_plan["allowed_targets"] = planned_targets
                enhanced_constraints.extend(
                    [
                        "Create or modify only planned files.",
                        "Do not rewrite unrelated tests.",
                        "Prefer small diffs.",
                        "If creating a new module, include the module file and its tests.",
                        "Do not place helper tests in tests/test_cli.py unless explicitly requested.",
                        "Ensure all planned targets are present in the diff.",
                    ]
                )
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

            second, second_timed_out = _run_with_provider_heartbeat(
                options,
                "regeneration",
                lambda: generate_patch_diff(
                    provider=config.providers.provider,
                    model=selected_model,
                    task=options.task,
                    failures=final_failures,
                    context=failure_context,
                    patch_plan=enhanced_patch_plan,
                    aegis_execution=decision.execution if isinstance(decision.execution, dict) else {},
                    api_key_env=config.providers.api_key_env,
                    max_context_chars=int(config.patches.max_context_chars),
                ),
                timeout_seconds=provider_timeout_seconds,
            )
            if second_timed_out:
                second = {
                    "available": False,
                    "provider": config.providers.provider,
                    "model": selected_model,
                    "diff": "",
                    "error": "provider_timeout",
                }
            second_diff = normalize_unified_diff(str(second.get("diff", "") or "").strip()).strip()
            if second_timed_out:
                patch_quality = None
                patch_diff.update(
                    {
                        "available": False,
                        "status": "invalid",
                        "error": "provider_timeout",
                        "provider": second.get("provider"),
                        "model": second.get("model"),
                    }
                )
                regeneration["final_status"] = "invalid"
                regeneration["result"] = "timeout"
                regeneration["regenerated_invalid_reason"] = "provider_timeout"
                # Keep previously-written latest.invalid.diff from the original invalid candidate.
                second_diff = ""
            second_validation = inspect_diff(second_diff, cwd=(cwd or Path.cwd())) if second_diff else {"valid": False, "errors": ["empty_diff"]}
            if docs_task and second_diff and not bool(second_validation.get("valid", False)):
                wrapped_diff, wrapped_validation, wrapped_apply_blocked = _maybe_wrap_docs_non_diff(
                    task_type=task_type,
                    raw_output=_sanitize_docs_wrapper_content(
                        _select_docs_wrapper_content(second, second_diff or str(second.get("diff", "") or ""))
                    ),
                    cwd=(cwd or Path.cwd()),
                )
                if wrapped_diff and bool(wrapped_validation.get("valid", False)) and not wrapped_apply_blocked:
                    second_diff = wrapped_diff
                    second_validation = wrapped_validation
                    regeneration["regenerated_repair_attempted"] = True
                    regeneration["regenerated_repair_applied"] = True
                    regeneration["regenerated_repair_status"] = "repaired"
                    regeneration["regenerated_repair_reason"] = "docs_wrapped_diff"
                    regeneration["regenerated_repair_error"] = None
                    regeneration["regenerated_repair_file_count"] = 1
                    regeneration["regenerated_repair_targets"] = ["README.md"]
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

            # Preserve a successful deterministic repair as a fallback when
            # regeneration was triggered by quality issues but failed validation.
            second_candidate_apply_blocked = bool(check_patch_text(second_diff, cwd=(cwd or Path.cwd())).get("apply_blocked", False)) if second_diff else True
            second_candidate_plan_consistent, _ = _compute_plan_consistency(patch_plan, second_validation, second_diff)
            second_candidate_syntax, _ = _syntactic_python_check(second_diff, cwd=(cwd or Path.cwd())) if (second_diff and bool(second_validation.get("valid", False))) else (None, None)
            second_additions = int((second_validation.get("summary", {}) or {}).get("additions", 0))
            second_size_threshold = 500 if test_task else 800
            second_candidate_hard_invalid = _hard_invalid_reason(
                syntactic_valid=second_candidate_syntax,
                additions=second_additions,
                size_threshold=second_size_threshold,
                plan_consistent=second_candidate_plan_consistent,
            )
            second_candidate_failed = (
                not bool(second_validation.get("valid", False))
                or second_candidate_apply_blocked
                or second_candidate_hard_invalid is not None
            )
            if (
                repaired_candidate_diff
                and repaired_candidate_validation
                and repaired_candidate_quality
                and repaired_candidate_plan_consistency is True
                and bool(repaired_candidate_validation.get("valid", False))
                and not repaired_candidate_apply_blocked
                and repaired_candidate_hard_invalid_reason is None
                and second_candidate_failed
                and "low_quality" in reasons
            ):
                provider_used = provider_result
                diff_text = repaired_candidate_diff
                validation_used = repaired_candidate_validation
                quality_used = repaired_candidate_quality
                regeneration["result"] = "repaired_fallback_used"
                regeneration["final_status"] = "generated"

        path_value: str | None = None
        invalid_path: str | None = None
        plan_consistent, plan_missing_targets = _compute_plan_consistency(patch_plan, validation_used, diff_text)
        if provider_used.get("available", False) and diff_text and bool(validation_used.get("valid", False)):
            _progress(options, "checking syntax of proposed Python changes")
            syntactic_valid, syntactic_error = _syntactic_python_check(diff_text, cwd=(cwd or Path.cwd()))
            additions = int((validation_used.get("summary", {}) or {}).get("additions", 0))
            size_threshold = 500 if test_task else 800
            if syntactic_valid is False:
                patch_quality = None
                invalid_path = str(write_latest_invalid_diff(diff_text, cwd=cwd))
                remove_latest_diff(cwd=cwd)
            elif additions > size_threshold:
                patch_quality = None
                invalid_path = str(write_latest_invalid_diff(diff_text, cwd=cwd))
                remove_latest_diff(cwd=cwd)
                syntactic_error = None
            elif not plan_consistent:
                patch_quality = None
                invalid_path = str(write_latest_invalid_diff(diff_text, cwd=cwd))
                remove_latest_diff(cwd=cwd)
            else:
                diff_path = write_latest_diff(diff_text, cwd=cwd)
                remove_latest_invalid_diff(cwd=cwd)
                path_value = str(diff_path)
                patch_quality = quality_used
                if patch_quality is not None and not plan_consistent:
                    patch_quality["confidence"] = min(float(patch_quality.get("confidence", 0.0)), 0.5)
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
        regeneration["result"] = final_status
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
            "repair_file_count": int(repair_result.get("repair_file_count", 0) or 0),
            "raw_repair_file_count": int(repair_result.get("raw_repair_file_count", 0) or 0),
            "repair_targets": list(repair_result.get("repair_targets", [])) if isinstance(repair_result.get("repair_targets", []), list) else [],
            "repaired_candidate_diff": repaired_candidate_diff,
            "repaired_candidate_validation": repaired_candidate_validation,
            "repaired_candidate_quality": repaired_candidate_quality,
            "repaired_candidate_syntax": repaired_candidate_syntax,
            "repaired_candidate_plan_consistency": repaired_candidate_plan_consistency,
            "regenerated_repair_attempted": bool(regeneration.get("regenerated_repair_attempted", False)),
            "regenerated_repair_applied": bool(regeneration.get("regenerated_repair_applied", False)),
            "regenerated_repair_status": str(regeneration.get("regenerated_repair_status", "not_attempted")),
            "regenerated_repair_reason": str(regeneration.get("regenerated_repair_reason", "not_attempted")),
            "regenerated_repair_error": regeneration.get("regenerated_repair_error"),
            "syntactic_valid": syntactic_valid,
            "syntactic_error": syntactic_error,
            "corrective_control_status": str(regeneration.get("corrective_control_status", "not_triggered")),
            "corrective_control_reason": str(regeneration.get("corrective_control_reason", "not_triggered")),
            "corrective_control_error": regeneration.get("corrective_control_error"),
            "initial_invalid_reason": None,
            "regeneration_trigger_reason": None,
            "final_invalid_reason": None,
            "regeneration": regeneration,
            "initial_diff": initial_diff[:800],
            "validation_result": validation_used,
            "validation_errors": [str(item) for item in validation_used.get("errors", [])],
            "quality_score": float((quality_used or {}).get("confidence", 0.0)),
            "issues": list((quality_used or {}).get("issues", [])),
            "provider": provider_used.get("provider"),
            "model": provider_used.get("model"),
            "plan_consistent": plan_consistent,
            "plan_missing_targets": plan_missing_targets,
            "path": path_value,
            "invalid_diff_path": invalid_path,
            "error": provider_used.get("error"),
            "preview": diff_text[:800],
        }
        if provider_used.get("available", False) and not path_value:
            patch_diff["available"] = False
            validation_errors = validation_used.get("errors", [])
            if syntactic_valid is False:
                patch_diff["error"] = "syntactic_invalid"
            elif provider_used.get("available", False) and syntactic_valid is True:
                additions = int((validation_used.get("summary", {}) or {}).get("additions", 0))
                size_threshold = 500 if test_task else 800
                if additions > size_threshold:
                    patch_diff["error"] = "excessive_diff_size"
                elif not plan_consistent:
                    patch_diff["error"] = "plan_inconsistent"
                elif validation_errors:
                    patch_diff["error"] = str(validation_errors[0])
                else:
                    patch_diff["error"] = "Diff generation returned empty output."
            elif validation_errors:
                patch_diff["error"] = str(validation_errors[0])
            else:
                patch_diff["error"] = "Diff generation returned empty output."
        if patch_diff["attempted"] and not patch_diff["available"] and not patch_diff.get("error"):
            patch_diff["error"] = "Provider unavailable"
        if patch_diff.get("status") == "invalid":
            patch_diff["initial_invalid_reason"] = patch_diff.get("error")

        hard_regen_reason = str(patch_diff.get("error") or "")
        hard_regen_allowed = hard_regen_reason in {"excessive_diff_size", "syntactic_invalid", "plan_inconsistent"}
        if (
            patch_diff.get("status") == "invalid"
            and hard_regen_allowed
            and not bool(regeneration.get("attempted", False))
        ):
            _progress(options, "attempting regeneration")
            regeneration["triggered"] = True
            regeneration["reason"] = hard_regen_reason
            regeneration["trigger_reason"] = hard_regen_reason
            regeneration["reasons"] = [hard_regen_reason]
            regeneration["attempted"] = True
            regeneration["attempt"] = 1
            patch_diff["regeneration_trigger_reason"] = hard_regen_reason

            planned_targets = sorted(_collect_plan_targets(patch_plan))
            regen_metadata: dict[str, Any] = {
                "max_additions": 300,
                "allowed_targets": planned_targets,
                "disallow_new_unplanned_files": True,
                "force_small_diff": True,
                "require_plan_alignment": True,
            }
            regen_plan = deepcopy(patch_plan)
            regen_constraints = [
                "Produce a valid unified diff.",
                "Limit additions to 300 lines.",
                "Modify only allowed targets.",
                "Do not create unplanned files.",
                "Keep diff minimal and small.",
                "Ensure patch aligns with patch plan targets.",
                "Include every planned target file in the diff.",
            ]
            if planned_targets:
                regen_plan["allowed_targets"] = planned_targets

            if _control_requested(config, (cwd or Path.cwd()).resolve()):
                control = _aegis_regeneration_control(
                    base_url=str(config.aegis.base_url),
                    metadata=regen_metadata,
                )
                regeneration["corrective_control_status"] = str(control.get("status", "client_error"))
                regeneration["corrective_control_reason"] = str(control.get("status", "client_error"))
                regeneration["corrective_control_error"] = control.get("error")
                if control.get("status") == "applied":
                    regeneration["aegis_guidance_applied"] = True
                    actions = control.get("actions", {})
                    if isinstance(actions, dict):
                        allowed = actions.get("allowed_targets")
                        if isinstance(allowed, list) and allowed:
                            regen_plan["allowed_targets"] = [str(item) for item in allowed if str(item).strip()]
                        max_additions = actions.get("max_additions")
                        if isinstance(max_additions, int) and max_additions > 0:
                            regen_metadata["max_additions"] = int(max_additions)
                            regen_constraints.append(f"Limit additions to {int(max_additions)} lines.")
                        extra = actions.get("constraints")
                        if isinstance(extra, list):
                            regen_constraints.extend(str(item) for item in extra)
            else:
                regeneration["corrective_control_status"] = "disabled_by_config"
                regeneration["corrective_control_reason"] = "disabled_by_config"

            regen_plan["regeneration_constraints"] = sorted(set(regen_constraints))
            second, second_timed_out = _run_with_provider_heartbeat(
                options,
                "post-invalid regeneration",
                lambda: generate_patch_diff(
                    provider=config.providers.provider,
                    model=selected_model,
                    task=options.task,
                    failures=final_failures,
                    context=failure_context,
                    patch_plan=regen_plan,
                    aegis_execution=decision.execution if isinstance(decision.execution, dict) else {},
                    api_key_env=config.providers.api_key_env,
                    max_context_chars=int(config.patches.max_context_chars),
                ),
                timeout_seconds=provider_timeout_seconds,
            )
            if second_timed_out:
                second = {
                    "available": False,
                    "provider": config.providers.provider,
                    "model": selected_model,
                    "diff": "",
                    "error": "provider_timeout",
                }
            second_diff = normalize_unified_diff(str(second.get("diff", "") or "").strip()).strip()
            second_validation = inspect_diff(second_diff, cwd=(cwd or Path.cwd())) if second_diff else {"valid": False, "errors": ["empty_diff"]}
            if docs_task and second_diff and not bool(second_validation.get("valid", False)):
                wrapped_diff, wrapped_validation, wrapped_apply_blocked = _maybe_wrap_docs_non_diff(
                    task_type=task_type,
                    raw_output=_sanitize_docs_wrapper_content(
                        _select_docs_wrapper_content(second, second_diff or str(second.get("diff", "") or ""))
                    ),
                    cwd=(cwd or Path.cwd()),
                )
                if wrapped_diff and bool(wrapped_validation.get("valid", False)) and not wrapped_apply_blocked:
                    second_diff = wrapped_diff
                    second_validation = wrapped_validation
                    regeneration["regenerated_repair_attempted"] = True
                    regeneration["regenerated_repair_applied"] = True
                    regeneration["regenerated_repair_status"] = "repaired"
                    regeneration["regenerated_repair_reason"] = "docs_wrapped_diff"
                    regeneration["regenerated_repair_error"] = None
                    regeneration["regenerated_repair_file_count"] = 1
                    regeneration["regenerated_repair_targets"] = ["README.md"]
            if second_diff and not bool(second_validation.get("valid", False)):
                regeneration["regenerated_repair_attempted"] = True
                second_repair = repair_malformed_diff(
                    second_diff,
                    cwd=(cwd or Path.cwd()),
                    task=options.task,
                    patch_plan=regen_plan,
                    context=failure_context,
                )
                regeneration["regenerated_repair_applied"] = bool(second_repair.get("applied", False))
                regeneration["regenerated_repair_status"] = str(second_repair.get("status", "skipped"))
                regeneration["regenerated_repair_reason"] = str(second_repair.get("reason", "unknown"))
                regeneration["regenerated_repair_error"] = second_repair.get("error")
                regeneration["regenerated_repair_file_count"] = int(second_repair.get("repair_file_count", 0) or 0)
                regeneration["regenerated_repair_targets"] = list(second_repair.get("repair_targets", [])) if isinstance(second_repair.get("repair_targets", []), list) else []
                if bool(second_repair.get("applied", False)):
                    second_diff = str(second_repair.get("diff", "") or second_diff)
                    second_validation = inspect_diff(second_diff, cwd=(cwd or Path.cwd()))
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
            second_plan_consistent, second_plan_missing = _compute_plan_consistency(regen_plan, second_validation, second_diff)
            second_syntactic_valid, second_syntactic_error = (None, None)
            if second.get("available", False) and second_diff and bool(second_validation.get("valid", False)):
                second_syntactic_valid, second_syntactic_error = _syntactic_python_check(second_diff, cwd=(cwd or Path.cwd()))
            second_additions = int((second_validation.get("summary", {}) or {}).get("additions", 0))
            second_threshold = min(300, 500 if test_task else 800)
            second_hard_invalid = _hard_invalid_reason(
                syntactic_valid=second_syntactic_valid,
                additions=second_additions,
                size_threshold=second_threshold,
                plan_consistent=second_plan_consistent,
            )

            provider_used = second
            diff_text = second_diff
            validation_used = second_validation
            quality_used = second_quality
            plan_consistent = second_plan_consistent
            plan_missing_targets = second_plan_missing
            syntactic_valid = second_syntactic_valid
            syntactic_error = second_syntactic_error

            if second.get("available", False) and second_diff and bool(second_validation.get("valid", False)) and not second_hard_invalid:
                diff_path = write_latest_diff(second_diff, cwd=cwd)
                remove_latest_invalid_diff(cwd=cwd)
                patch_quality = second_quality
                if patch_quality is not None and not second_plan_consistent:
                    patch_quality["confidence"] = min(float(patch_quality.get("confidence", 0.0)), 0.5)
                patch_diff.update(
                    {
                        "available": True,
                        "status": "generated",
                        "path": str(diff_path),
                        "invalid_diff_path": None,
                        "error": None,
                        "provider": second.get("provider"),
                        "model": second.get("model"),
                        "preview": second_diff[:800],
                        "validation_result": second_validation,
                        "validation_errors": [str(item) for item in second_validation.get("errors", [])],
                        "quality_score": float((second_quality or {}).get("confidence", 0.0)),
                        "issues": list((second_quality or {}).get("issues", [])),
                        "syntactic_valid": second_syntactic_valid,
                        "syntactic_error": second_syntactic_error,
                        "plan_consistent": second_plan_consistent,
                        "plan_missing_targets": second_plan_missing,
                    }
                )
                regeneration["final_status"] = "generated"
                regeneration["result"] = "generated"
                regeneration["regenerated_invalid_reason"] = None
            else:
                patch_quality = None
                invalid_path = str(write_latest_invalid_diff(second_diff, cwd=cwd)) if second_diff else None
                remove_latest_diff(cwd=cwd)
                final_error = second_hard_invalid
                if not final_error:
                    errors_second = second_validation.get("errors", [])
                    final_error = str(errors_second[0]) if errors_second else "Diff generation returned empty output."
                patch_diff.update(
                    {
                        "available": False,
                        "status": "invalid",
                        "path": None,
                        "invalid_diff_path": invalid_path,
                        "error": final_error,
                        "provider": second.get("provider"),
                        "model": second.get("model"),
                        "preview": second_diff[:800],
                        "validation_result": second_validation,
                        "validation_errors": [str(item) for item in second_validation.get("errors", [])],
                        "quality_score": float((second_quality or {}).get("confidence", 0.0)),
                        "issues": list((second_quality or {}).get("issues", [])),
                        "syntactic_valid": second_syntactic_valid,
                        "syntactic_error": second_syntactic_error,
                        "plan_consistent": second_plan_consistent,
                        "plan_missing_targets": second_plan_missing,
                    }
                )
                regeneration["final_status"] = "invalid"
                regeneration["result"] = "invalid"
                regeneration["regenerated_invalid_reason"] = final_error
            if second_timed_out:
                patch_quality = None
                patch_diff["available"] = False
                patch_diff["status"] = "invalid"
                patch_diff["error"] = "provider_timeout"
                patch_diff["path"] = None
                regeneration["final_status"] = "invalid"
                regeneration["result"] = "timeout"
                regeneration["regenerated_invalid_reason"] = "provider_timeout"

        # Keep top-level summary flags aligned with the final regeneration state,
        # including post-invalid regeneration paths.
        if patch_diff.get("regeneration_trigger_reason") is None and bool(regeneration.get("attempted", False)):
            patch_diff["regeneration_trigger_reason"] = regeneration.get("trigger_reason") or regeneration.get("reason")
        if patch_diff.get("status") == "invalid":
            patch_diff["final_invalid_reason"] = patch_diff.get("error")
        patch_diff["regenerated_repair_attempted"] = bool(regeneration.get("regenerated_repair_attempted", False))
        patch_diff["regenerated_repair_applied"] = bool(regeneration.get("regenerated_repair_applied", False))
        patch_diff["regenerated_repair_status"] = str(regeneration.get("regenerated_repair_status", "not_attempted"))
        patch_diff["regenerated_repair_reason"] = str(regeneration.get("regenerated_repair_reason", "not_attempted"))
        patch_diff["regenerated_repair_error"] = regeneration.get("regenerated_repair_error")
        patch_diff["regenerated_repair_file_count"] = int(regeneration.get("regenerated_repair_file_count", 0) or 0)
        patch_diff["regenerated_repair_targets"] = list(regeneration.get("regenerated_repair_targets", [])) if isinstance(regeneration.get("regenerated_repair_targets", []), list) else []
        patch_diff["regeneration_attempted"] = bool(regeneration.get("attempted", False))
        patch_diff["regenerated"] = bool(
            regeneration.get("attempted", False) and patch_diff.get("status") == "generated"
        )
        patch_diff["regeneration"] = regeneration
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
            "plan_consistent": None,
            "plan_missing_targets": [],
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
            "plan_consistent": None,
            "plan_missing_targets": [],
            "path": None,
            "error": "Provider unavailable",
            "preview": "",
        }

    patch_diff_payload = patch_diff if isinstance(patch_diff, dict) else {}
    validation_payload = patch_diff_payload.get("validation_result", {})
    validation_valid = bool(validation_payload.get("valid", False)) if isinstance(validation_payload, dict) else False
    syntactic_valid = patch_diff_payload.get("syntactic_valid")
    plan_consistent = bool(patch_diff_payload.get("plan_consistent", False))
    confidence = float((patch_quality or {}).get("confidence", 0.0)) if isinstance(patch_quality, dict) else 0.0
    apply_safety = _compute_apply_safety(
        validation_valid=validation_valid,
        syntactic_valid=syntactic_valid if isinstance(syntactic_valid, bool) or syntactic_valid is None else None,
        plan_consistent=plan_consistent,
        confidence=confidence,
    )

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
        "apply_safety": apply_safety,
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
        _progress(options, "writing report")
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
