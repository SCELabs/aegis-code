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
from aegis_code.aegis_adapter import get_aegis_guidance
from aegis_code.budget import BudgetState
from aegis_code.config import load_config
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.probe import get_capabilities
from aegis_code.context.failure_context import build_failure_context
from aegis_code.context.repo_scan import build_python_repo_map, scan_repo
from aegis_code.execution_loop import should_retry_tests, synthesize_symptoms
from aegis_code.impact.resolver import extract_failure_signals, impact_report_to_dict, resolve_impact
from aegis_code.models import CommandResult
from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.constraints import build_patch_constraints, detect_named_test_file
from aegis_code.patches.diff_evaluator import evaluate_diff
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.diff_normalizer import normalize_unified_diff
from aegis_code.patches.policy import hard_invalid_content_reason, hard_invalid_reason
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
from aegis_code.providers import generate_structured_edits
from aegis_code.patches.proposal_controller import build_proposal_contract, run_structured_proposal_controller
from aegis_code.report import write_reports
from aegis_code.routing import normalize_tier, resolve_model_for_tier
from aegis_code.safety.patch_review import safety_report_to_dict, scan_diff
from aegis_code.secrets import list_scoped_keys, resolve_key, resolve_key_source
from aegis_code.short_circuit import should_skip_provider
from aegis_code.sll_guidance import build_sll_fix_guidance
from aegis_code.sll_adapter import analyze_failures_sll, classify_sll_risk, run_sll_analysis
from aegis_code.tools.tests import run_configured_tests
from aegis_code.verification import resolve_verification_command

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
    command: str | None = None
    scope_contract: dict[str, Any] | None = None
    patch_operation: str | None = None


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
        "add endpoint",
        "add route",
        "api route",
        "add handler",
        "request body validation",
        "schema",
        "validation",
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


def _has_feature_implementation_intent(task: str) -> bool:
    lowered = str(task or "").lower().strip()
    feature_phrases = (
        "add endpoint",
        "add api route",
        "api route",
        "add route",
        "post /",
        "get /",
        "put /",
        "delete /",
        "add feature",
        "add handler",
        "implement handler",
        "add schema",
        "implement schema",
        "request body validation",
        "body validation",
        "payload validation",
    )
    if any(phrase in lowered for phrase in feature_phrases):
        return True
    if "implement" in lowered and any(token in lowered for token in ("endpoint", "route", "handler", "schema", "validation", "api")):
        return True
    return False


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
    if _has_feature_implementation_intent(lowered):
        return "feature_implementation"
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
    named = detect_named_test_file(task)
    if named:
        return named
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
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
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


def _build_append_diff(*, target_path: str, original_text: str, appended_content: str) -> str:
    append_text = str(appended_content or "")
    if append_text and not append_text.endswith("\n"):
        append_text += "\n"
    candidate = str(original_text or "") + append_text
    old_lines = str(original_text or "").splitlines()
    new_lines = candidate.splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _line_tail_capped(text: str, max_lines: int, max_chars: int) -> str:
    lines = str(text or "").splitlines()
    tail = lines[-max_lines:] if max_lines > 0 else lines
    rendered = "\n".join(tail)
    if len(rendered) <= max_chars:
        return rendered
    trimmed = rendered[-max_chars:]
    if "\n" in trimmed:
        trimmed = trimmed[trimmed.find("\n") + 1 :]
    return trimmed


def _build_append_target_context(*, cwd: Path, target_path: str, original_text: str) -> dict[str, Any]:
    imports: list[str] = []
    names: list[str] = []
    tests: list[str] = []
    js_style = "unknown"
    js_test_framework = "unknown"
    package_type = "commonjs"
    target_is_js = str(target_path).replace("\\", "/").lower().endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"))
    if target_is_js:
        package_json = cwd / "package.json"
        if package_json.exists():
            try:
                pkg = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
                if isinstance(pkg, dict):
                    package_type = str(pkg.get("type", "commonjs") or "commonjs").strip().lower()
            except Exception:
                package_type = "commonjs"
    for raw_line in str(original_text or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(stripped)
        fn_match = re.match(r"^\s*(?:async\s+def|def)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
        if fn_match:
            name = fn_match.group(1)
            names.append(name)
            if name.startswith("test_"):
                tests.append(name)
        class_test_match = re.match(r"^\s*def\s+(test_[A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
        if class_test_match:
            tests.append(class_test_match.group(1))
        if target_is_js:
            if stripped.startswith("import "):
                js_style = "esm"
            if "require(" in stripped and js_style == "unknown":
                js_style = "commonjs"
            if stripped.startswith("export ") or "module.exports" in stripped:
                names.append(stripped)
            js_fn_match = re.match(r"^\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", raw_line)
            if js_fn_match:
                names.append(js_fn_match.group(1))
            if "node:test" in stripped or " from \"node:test\"" in stripped or " from 'node:test'" in stripped:
                js_test_framework = "node:test"
            if "describe(" in stripped or "expect(" in stripped:
                if js_test_framework == "unknown":
                    js_test_framework = "jest_like"
    if target_is_js and js_style == "unknown":
        js_style = "esm" if package_type == "module" or str(target_path).endswith(".mjs") else "commonjs"
    return {
        "path": target_path,
        "imports": sorted(set(imports), key=str.lower)[:40],
        "existing_names": sorted(set(names), key=str.lower)[:80],
        "existing_tests": sorted(set(tests), key=str.lower)[:80],
        "js_module_system": js_style if target_is_js else "n/a",
        "js_test_framework": js_test_framework if target_is_js else "n/a",
        "package_json_type": package_type if target_is_js else "n/a",
        "tail": _line_tail_capped(original_text, 80, 4000),
    }


def _collect_defined_names(tree: ast.AST) -> set[str]:
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            defined.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(str(node.name))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = str(alias.asname or alias.name.split(".")[0]).strip()
                if bound:
                    defined.add(bound)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if str(alias.name) == "*":
                    continue
                bound = str(alias.asname or alias.name).strip()
                if bound:
                    defined.add(bound)
    return defined


def _append_python_sanity_error(*, target_path: str, original_text: str, appended_content: str) -> str | None:
    if not str(target_path).endswith(".py"):
        return None
    candidate = str(original_text or "") + str(appended_content or "")
    try:
        candidate_tree = ast.parse(candidate)
    except SyntaxError:
        return "append_syntax_invalid"
    try:
        appended_tree = ast.parse(str(appended_content or ""))
    except SyntaxError:
        return "append_syntax_invalid"
    defined_names = _collect_defined_names(candidate_tree)
    builtins_names = set(dir(__import__("builtins")))
    suspicious: set[str] = set()
    for node in ast.walk(appended_tree):
        if not isinstance(node, ast.keyword):
            continue
        value = node.value
        if not isinstance(value, ast.Name) or not isinstance(value.ctx, ast.Load):
            continue
        name = str(value.id or "")
        # Conservative heuristic: flag only obvious single-letter unresolved names.
        if len(name) == 1 and name not in defined_names and name not in builtins_names:
            suspicious.add(name)
    if suspicious:
        return "append_semantic_suspicious"
    return None


def _module_exists_for_python_m(cwd: Path, module_name: str) -> bool:
    rel = str(module_name or "").strip().replace(".", "/")
    if not rel:
        return False
    mod_file = (cwd / f"{rel}.py").resolve()
    pkg_init = (cwd / rel / "__init__.py").resolve()
    return mod_file.exists() or pkg_init.exists()


def _looks_like_test_python_target(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    name = Path(normalized).name
    return normalized.endswith(".py") and (normalized.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py"))


def _looks_like_docs_target(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return normalized == "readme.md" or normalized.startswith("docs/")


def _looks_like_js_target(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    return normalized.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"))


def _source_snippets_text(snippets: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in snippets:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).replace("\\", "/").lower().strip()
        if not path or path.startswith("tests/") or not path.endswith(".py"):
            continue
        parts.append(str(item.get("excerpt", "") or ""))
    return "\n".join(parts)


def _detect_simple_slugify_source(*, cwd: Path, source_text: str) -> bool:
    pattern = r"def\s+slugify\s*\(.*?\)\s*(?:->\s*[^:]+)?\s*:\s*[\r\n]+\s*return\s+text\.lower\(\)\.replace\(\s*['\"]\s+['\"],\s*['\"]-['\"]\s*\)"
    if re.search(pattern, source_text, flags=re.DOTALL):
        return True
    ignore_dirs = {
        ".git",
        ".aegis",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".pytest_cache",
    }
    candidates: list[Path] = []
    try:
        for path in sorted(cwd.rglob("*.py")):
            if any(part in ignore_dirs for part in path.parts):
                continue
            candidates.append(path)
            if len(candidates) >= 40:
                break
    except Exception:
        return False
    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if re.search(pattern, text, flags=re.DOTALL):
            return True
    return False


def _append_source_conflict_error(
    *,
    cwd: Path,
    target_path: str,
    appended_content: str,
    relevant_file_snippets: list[dict[str, Any]],
) -> str | None:
    appended = str(appended_content or "")
    source_text = _source_snippets_text(relevant_file_snippets)
    if _looks_like_js_target(target_path):
        normalized_path = str(target_path or "").replace("\\", "/").lower()
        cwd_pkg = cwd / "package.json"
        package_type = "commonjs"
        if cwd_pkg.exists():
            try:
                pkg = json.loads(cwd_pkg.read_text(encoding="utf-8", errors="replace"))
                if isinstance(pkg, dict):
                    package_type = str(pkg.get("type", "commonjs") or "commonjs").strip().lower()
            except Exception:
                package_type = "commonjs"
        is_esm = normalized_path.endswith(".mjs") or package_type == "module" or "import " in source_text or "export " in source_text
        if is_esm and "require(" in appended:
            return "append_source_conflict"
        target_text = ""
        try:
            target_text = ((cwd / normalized_path).resolve()).read_text(encoding="utf-8", errors="replace")
        except Exception:
            target_text = ""
        node_test_source = ("node:test" in source_text) or ("node:test" in target_text)
        if node_test_source and ("describe(" in appended or "expect(" in appended):
            return "append_source_conflict"
        if re.search(r"\bslugify\b", appended, flags=re.IGNORECASE) and re.search(r"\bslugify\b", source_text, flags=re.IGNORECASE) is None:
            return "append_source_conflict"
        if re.search(r"\bpython\s+-m\b", appended, flags=re.IGNORECASE):
            return "append_source_conflict"
    if _looks_like_docs_target(target_path):
        lowered = appended.lower()
        simple_slugify = _detect_simple_slugify_source(cwd=cwd, source_text=source_text)
        if simple_slugify:
            unsupported_docs_claims = (
                "punctuation",
                "special characters",
                "strip leading",
                "strip trailing",
                "trim whitespace",
                "url-safe",
                "sanitize",
                "cleanup",
                "arbitrary text cleanup",
            )
            if any(token in lowered for token in unsupported_docs_claims):
                return "append_source_conflict"
        return None
    if not _looks_like_test_python_target(target_path):
        return None
    snippet_paths = [
        str(item.get("path", "")).replace("\\", "/")
        for item in relevant_file_snippets
        if isinstance(item, dict) and str(item.get("path", "")).strip()
    ]

    py_m_matches = re.findall(r"python\s+-m\s+([A-Za-z_][A-Za-z0-9_\.]*)", appended)
    entrypoint_signal = (
        "src/main.py" in {p.lower() for p in snippet_paths}
        and "__main__" in source_text
    )
    if py_m_matches and entrypoint_signal:
        for mod in py_m_matches:
            if not _module_exists_for_python_m(cwd, mod):
                return "append_source_conflict"

    if "TODO_FILE" in appended:
        todo_file_fixed = re.search(r'TODO_FILE\s*=\s*Path\(["\']todo\.json["\']\)', source_text) is not None
        has_env_usage = "os.environ" in source_text
        if todo_file_fixed and not has_env_usage:
            return "append_source_conflict"

    expects_id = ('["id"]' in appended) or ("['id']" in appended) or ("todo_id" in appended)
    if expects_id:
        append_blocks = re.findall(r"todos\.append\(\s*\{([^}]*)\}\s*\)", source_text, flags=re.DOTALL)
        if append_blocks and all(("\"id\"" not in block and "'id'" not in block) for block in append_blocks):
            return "append_source_conflict"

    expects_done_word = re.search(r'["\']done["\']', appended, flags=re.IGNORECASE) is not None
    source_checkbox_output = ("[x]" in source_text) or ("[ ]" in source_text)
    if expects_done_word and source_checkbox_output:
        return "append_source_conflict"

    return None


def _parse_append_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, "append_output_invalid"
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, "append_output_invalid"
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, "append_output_invalid"
    if not isinstance(payload, dict):
        return False, None, "append_output_invalid"
    if "changes" in payload:
        return False, None, "append_output_invalid"
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, "append_output_invalid"
    if not content.strip():
        return True, "", None
    normalized = content if content.endswith("\n") else f"{content}\n"
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, "append_output_invalid"
    return True, normalized, None


def _validate_append_diff(*, diff_text: str, original_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, "invalid_append_operation"
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) != 0:
        return False, "invalid_append_operation"
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, "invalid_append_operation"
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    new_path = str(file_entry.get("new_path", "") or "")
    if new_path != target_path:
        return False, "invalid_append_operation"
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, "invalid_append_operation"
    return True, None


def _prioritize_patch_error(
    *,
    current_error: str | None,
    patch_plan: dict[str, Any],
    structured_patch: dict[str, Any],
    task_text: str,
    requested_operation: str,
) -> str | None:
    if not current_error:
        return None
    candidates: list[str] = []
    candidates.append(str(current_error))
    failure_reason = str(structured_patch.get("failure_reason", "") or "").strip()
    if failure_reason:
        candidates.append(failure_reason)
    if requested_operation == "append":
        # Preserve append parser semantics.
        if "no_append_needed" in candidates:
            return "no_append_needed"
        if "append_source_conflict" in candidates:
            return "append_source_conflict"
        if "append_syntax_invalid" in candidates:
            return "append_syntax_invalid"
        if "append_semantic_suspicious" in candidates:
            return "append_semantic_suspicious"
        if "append_output_invalid" in candidates:
            return "append_output_invalid"
        if "invalid_append_operation" in candidates:
            return "invalid_append_operation"

    lowered_task = str(task_text or "").lower()
    allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
    looks_additive_tests = (
        any(token in lowered_task for token in ("add test", "add tests", "write test", "write tests", "generate tests", "tests for"))
        and bool(allowed_targets)
        and all(path.startswith("tests/") for path in allowed_targets)
    )
    looks_additive_docs = (
        any(token in lowered_task for token in ("append doc", "append docs", "add docs", "add documentation"))
        and bool(allowed_targets)
        and all(path == "README.md" or path.startswith("docs/") for path in allowed_targets)
    )
    looks_additive_source = _is_additive_source_task(task_text, patch_plan)
    if (
        str(current_error or "") in {"structured_output_invalid", "invalid_diff"}
        and requested_operation != "append"
    ):
        if looks_additive_tests:
            candidates.append("destructive_test_rewrite")
        elif looks_additive_docs:
            candidates.append("destructive_docs_rewrite")
        elif looks_additive_source:
            candidates.append("destructive_source_rewrite")

    priority = {
        "destructive_test_rewrite": 0,
        "destructive_docs_rewrite": 1,
        "destructive_source_rewrite": 2,
        "no_append_needed": 3,
        "append_source_conflict": 4,
        "append_syntax_invalid": 5,
        "append_semantic_suspicious": 6,
        "invalid_append_operation": 7,
        "plan_inconsistent": 8,
        "append_output_invalid": 9,
        "structured_output_invalid": 10,
        "invalid_diff": 11,
    }
    if not candidates:
        return current_error
    best = sorted(candidates, key=lambda item: priority.get(str(item), 50))[0]
    return str(best)


def _is_additive_docs_task(task_text: str, patch_plan: dict[str, Any]) -> bool:
    lowered_task = str(task_text or "").lower()
    tokens = ("add readme", "add docs", "append docs", "add documentation", "usage examples", "add example", "add examples")
    if not any(token in lowered_task for token in tokens):
        return False
    allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
    if not allowed_targets:
        return True
    return all(path == "README.md" or path.startswith("docs/") for path in allowed_targets)


def _is_destructive_docs_rewrite(diff_text: str, task_text: str, patch_plan: dict[str, Any]) -> bool:
    if not _is_additive_docs_task(task_text, patch_plan):
        return False
    touched_paths = [
        line[6:].strip()
        for line in str(diff_text or "").splitlines()
        if line.startswith("+++ b/")
    ]
    if touched_paths and not all(path == "README.md" or path.startswith("docs/") for path in touched_paths):
        return False
    deleted_lines = [
        line[1:].strip()
        for line in str(diff_text or "").splitlines()
        if line.startswith("-") and not line.startswith("--- ")
    ]
    for line in deleted_lines:
        lowered = line.lower()
        if re.match(r"^#{1,6}\s+\S+", line):
            return True
        if re.match(r"^(summary|overview|tl;dr)\b", lowered):
            return True
    return False


def _is_additive_source_task(task_text: str, patch_plan: dict[str, Any]) -> bool:
    lowered_task = str(task_text or "").lower()
    if not any(token in lowered_task for token in ("add ", "append ", "new ")):
        return False
    if any(token in lowered_task for token in ("readme", "docs", "documentation", "test", "tests")):
        return False
    allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
    if not allowed_targets:
        return False
    return all(not path.startswith("tests/") and path != "README.md" and not path.startswith("docs/") for path in allowed_targets)


def _is_destructive_source_rewrite(diff_text: str, task_text: str, patch_plan: dict[str, Any]) -> bool:
    if not _is_additive_source_task(task_text, patch_plan):
        return False
    deleted_lines = [
        line[1:].strip()
        for line in str(diff_text or "").splitlines()
        if line.startswith("-") and not line.startswith("--- ")
    ]
    if len([line for line in deleted_lines if line]) >= 8:
        return True
    for line in deleted_lines:
        if re.search(r"\b(module\.exports|exports\.|export\s+\{?|export\s+default)\b", line):
            return True
    return False


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


def _attach_repo_map(context: dict[str, Any] | None, repo_map: dict[str, Any]) -> dict[str, Any]:
    payload = context if isinstance(context, dict) else {}
    files = payload.get("files", [])
    if not isinstance(files, list):
        files = []
    enriched = dict(payload)
    enriched["files"] = files
    enriched["repo_map"] = repo_map
    return enriched


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
    diff_text: str = "",
    validation: dict[str, Any] | None = None,
    test_task: bool = False,
    task_text: str = "",
) -> str | None:
    return hard_invalid_reason(
        syntactic_valid=syntactic_valid,
        additions=additions,
        size_threshold=size_threshold,
        plan_consistent=plan_consistent,
        diff_text=diff_text,
        validation=validation,
        test_task=test_task,
        task_text=task_text,
    )


def _hard_invalid_content_reason(
    *,
    diff_text: str,
    validation: dict[str, Any],
    test_task: bool,
    task_text: str,
) -> str | None:
    return hard_invalid_content_reason(
        diff_text=diff_text,
        validation=validation,
        test_task=test_task,
        task_text=task_text,
    )


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


def _build_feature_plan(
    *,
    command: str,
    requested_operation: str,
    explicit_scope_active: bool,
    explicit_scope: dict[str, Any],
    patch_plan: dict[str, Any],
    cwd: Path,
    task_text: str,
    baseline_healthy: bool,
) -> dict[str, Any] | None:
    if str(command or "").strip().lower() != "patch":
        return None
    if requested_operation == "append":
        return None
    if not explicit_scope_active:
        return None
    if not baseline_healthy:
        return None
    task_type = str(patch_plan.get("task_type", "") or "general")
    if "fix failing tests in " in str(task_text or "").lower():
        return None
    scope_targets = [
        _normalize_rel_path(str(item))
        for item in explicit_scope.get("allowed_targets", [])
        if str(item).strip()
    ] if isinstance(explicit_scope.get("allowed_targets", []), list) else []
    if task_type == "docs_task" and scope_targets and all(path == "README.md" or path.startswith("docs/") for path in scope_targets):
        return None
    if len(scope_targets) <= 1:
        return None

    proposed_changes = patch_plan.get("proposed_changes", []) if isinstance(patch_plan.get("proposed_changes", []), list) else []
    proposed_by_file: dict[str, dict[str, Any]] = {}
    for item in proposed_changes:
        if not isinstance(item, dict):
            continue
        path = _normalize_rel_path(str(item.get("file", "") or ""))
        if path and path not in proposed_by_file:
            proposed_by_file[path] = item

    allowed_ops = [
        str(item).strip().lower()
        for item in explicit_scope.get("allowed_operations", [])
        if str(item).strip()
    ] if isinstance(explicit_scope.get("allowed_operations", []), list) else []
    allow_new = bool(explicit_scope.get("allow_new_files", False))

    steps: list[dict[str, Any]] = []
    for idx, target in enumerate(scope_targets, start=1):
        op = "replace"
        if allowed_ops == ["create"]:
            op = "create"
        elif "create" in allowed_ops and "replace" not in allowed_ops:
            op = "create"
        elif allow_new and "create" in allowed_ops:
            exists = ((cwd / target).resolve()).exists()
            op = "replace" if exists else "create"
        change = proposed_by_file.get(target, {})
        description = str(change.get("description", "") or "").strip()
        intent = description or f"Apply requested task changes to {target}."
        steps.append(
            {
                "id": f"step_{idx}",
                "target_file": target,
                "operation": op,
                "intent": intent,
                "max_changed_lines": 300,
                "status": "planned",
            }
        )

    return {
        "available": True,
        "kind": "phase1_planning",
        "steps": steps,
    }


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
    capped = text[:max_chars_per_file]
    newline_idx = capped.rfind("\n")
    if newline_idx == -1:
        return "[context truncated for runtime context budget]"
    kept = capped[: newline_idx + 1]
    return kept + "[context truncated for runtime context budget]"


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


_SNIPPET_MAX_FILES = 6
_SNIPPET_MAX_CHARS_PER_FILE = 900
_SNIPPET_MAX_TOTAL_CHARS = 3600


def _candidate_python_excerpt(text: str, max_chars: int) -> str:
    lines = str(text or "").splitlines()
    if not lines:
        return ""
    hit_indexes: list[int] = []
    patterns = (
        r"^\s*(?:async\s+def|def)\s+",
        r"^\s*class\s+",
        r"\bmain\s*\(",
        r"\bsys\.argv\b",
        r"\bargparse\b",
        r"\bprint\s*\(",
        r"^[A-Z][A-Z0-9_]{1,}\s*=",
    )
    combined = re.compile("|".join(patterns))
    for idx, line in enumerate(lines):
        if combined.search(line):
            hit_indexes.append(idx)
    if not hit_indexes:
        tail = "\n".join(lines[-40:])
        return tail[-max_chars:] if len(tail) > max_chars else tail
    selected: list[int] = []
    for idx in hit_indexes:
        for pos in range(max(0, idx - 2), min(len(lines), idx + 4)):
            selected.append(pos)
    selected = sorted(set(selected))
    chunks: list[str] = []
    prev = -2
    for idx in selected:
        if idx > prev + 1 and chunks:
            chunks.append("...")
        chunks.append(lines[idx])
        prev = idx
    rendered = "\n".join(chunks).strip()
    if len(rendered) <= max_chars:
        return rendered
    capped = rendered[:max_chars]
    nl = capped.rfind("\n")
    return (capped[:nl] if nl > 0 else capped).rstrip()


def _collect_repo_map_paths(repo_map: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for section in ("source_files", "test_files"):
        items = repo_map.get(section, []) if isinstance(repo_map, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if path:
                out.append(path)
    return out


def _build_relevant_file_snippets(
    *,
    cwd: Path,
    patch_plan: dict[str, Any],
    failure_context: dict[str, Any],
    repo_map: dict[str, Any],
) -> list[dict[str, str]]:
    root = cwd.resolve()
    explicit_targets = [
        str(item).strip().replace("\\", "/")
        for item in patch_plan.get("allowed_targets", [])
        if str(item).strip()
    ] if isinstance(patch_plan.get("allowed_targets", []), list) else []
    proposed_targets = []
    proposed = patch_plan.get("proposed_changes", []) if isinstance(patch_plan.get("proposed_changes", []), list) else []
    for item in proposed:
        if isinstance(item, dict):
            value = str(item.get("file", "")).strip().replace("\\", "/")
            if value:
                proposed_targets.append(value)
    context_targets = _extract_context_paths(failure_context)
    cli_targets = []
    cli_hints = repo_map.get("cli_hints", {}) if isinstance(repo_map, dict) else {}
    if isinstance(cli_hints, dict):
        for key in ("main_guard_files", "main_function_files", "argparse_files", "sys_argv_files"):
            vals = cli_hints.get(key, [])
            if isinstance(vals, list):
                cli_targets.extend(str(v).strip().replace("\\", "/") for v in vals if str(v).strip())
    repo_targets = _collect_repo_map_paths(repo_map)

    ranked: dict[str, tuple[int, str]] = {}
    def _add(paths: list[str], score: int) -> None:
        for p in paths:
            path = str(p).strip().replace("\\", "/")
            if not path or path in ranked:
                continue
            ranked[path] = (score, path.lower())
    _add(explicit_targets, 0)
    _add(proposed_targets, 1)
    _add(context_targets, 2)
    _add(cli_targets, 3)
    _add(repo_targets, 4)

    ordered = [path for path, _meta in sorted(ranked.items(), key=lambda kv: kv[1])][: _SNIPPET_MAX_FILES]
    snippets: list[dict[str, str]] = []
    total = 0
    for rel in ordered:
        target = (root / rel).resolve()
        try:
            target.relative_to(root)
        except Exception:
            continue
        if not target.exists() or not target.is_file() or _is_ignored_path(Path(rel)):
            continue
        text = _read_context_file(target, max_chars_per_file=4000)
        excerpt = _candidate_python_excerpt(text, _SNIPPET_MAX_CHARS_PER_FILE if rel.endswith(".py") else 700)
        if not excerpt.strip():
            continue
        remaining = _SNIPPET_MAX_TOTAL_CHARS - total
        if remaining <= 0:
            break
        if len(excerpt) > remaining:
            excerpt = excerpt[:remaining]
            nl = excerpt.rfind("\n")
            excerpt = (excerpt[:nl] if nl > 0 else excerpt).rstrip()
            if not excerpt:
                break
        snippets.append({"path": rel, "excerpt": excerpt})
        total += len(excerpt)
    return snippets


def _attach_relevant_file_snippets(
    *,
    context: dict[str, Any],
    cwd: Path,
    patch_plan: dict[str, Any],
    repo_map: dict[str, Any],
) -> dict[str, Any]:
    enriched = dict(context) if isinstance(context, dict) else {"files": []}
    snippets = _build_relevant_file_snippets(
        cwd=cwd,
        patch_plan=patch_plan,
        failure_context=context if isinstance(context, dict) else {"files": []},
        repo_map=repo_map if isinstance(repo_map, dict) else {},
    )
    enriched["relevant_file_snippets"] = snippets
    return enriched


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
    remove_latest_diff(cwd=cwd)
    remove_latest_invalid_diff(cwd=cwd)
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

    capabilities = get_capabilities(cwd or Path.cwd())
    detected_capabilities = detect_capabilities(cwd or Path.cwd())
    mode = options.mode or config.mode
    budget = BudgetState(total=options.budget if options.budget is not None else config.budget_per_task)

    repo_summary = scan_repo(cwd)
    repo_map = build_python_repo_map(cwd)
    commands_run: list[dict[str, Any]] = []
    failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    initial_failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    final_failures: dict[str, Any] = {"failed_tests": [], "failure_count": 0}
    failure_context: dict[str, Any] = _attach_repo_map({"files": []}, repo_map)
    sll_analysis: dict[str, Any] = {"available": False}
    sll_pre_call: dict[str, Any] = {"available": False}
    sll_post_call: dict[str, Any] = {"available": False}
    sll_risk = "low"
    sll_fix_guidance: dict[str, Any] = {
        "strategy": "unknown",
        "constraints": [],
        "notes": "No structural guidance available.",
    }
    symptoms: list[str] = ["unstable_workflow"]
    test_attempts: list[dict[str, Any]] = []
    patch_plan: dict[str, Any] = {
        "strategy": "Failure analysis disabled.",
        "confidence": 0.0,
        "proposed_changes": [],
    }
    patch_diff: dict[str, Any] = _patch_diff_default()
    structured_patch: dict[str, Any] = {
        "attempted": False,
        "available": False,
        "status": "skipped",
        "errors": [],
        "files": [],
        "fallback": None,
        "failure_reason": None,
        "retry_attempted": False,
        "retry_count": 0,
        "next_actions": [],
        "allowed_targets": [],
        "missing_targets": [],
    }
    feature_plan: dict[str, Any] | None = None
    patch_quality: dict[str, Any] | None = None
    patch_safety: dict[str, Any] | None = None
    aegis_guidance: dict[str, Any] = {"available": False, "actions": [], "explanation": "", "used_fallback": False}
    provider_skipped = False
    skip_reason = ""
    next_action: str | None = None
    retry_policy: dict[str, Any] = {
        "max_retries": 0,
        "allow_escalation": False,
        "retry_attempted": False,
        "retry_count": 0,
        "stopped_reason": "not_evaluated",
    }
    resolved_verification = resolve_verification_command((cwd or Path.cwd()).resolve())
    selected_test_command = str(resolved_verification.get("command") or "").strip()
    verification: dict[str, Any] = {
        "available": bool(resolved_verification.get("available", False)),
        "test_command": selected_test_command or None,
        "command": selected_test_command or None,
        "source": str(resolved_verification.get("source", "none") or "none"),
        "observed": bool(resolved_verification.get("observed", False)),
        "detected_stack": capabilities.get("detected_stack") or detected_capabilities.get("detected_stack"),
        "confidence": capabilities.get("verification_confidence", detected_capabilities.get("confidence", "low")),
        "reason": str(resolved_verification.get("source", "none") or "none"),
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
        test_command = selected_test_command
        decision = None
        if test_command:
            _progress(options, f"running verification command: {test_command}")
            initial_result: CommandResult = run_configured_tests(test_command, cwd=cwd)
            commands_run.append(initial_result.to_dict())
            initial_failures = parse_pytest_output(initial_result.full_output)
            final_failures = initial_failures
            failure_context = _attach_repo_map(
                build_failure_context(final_failures.get("failed_tests", []), cwd or Path.cwd()),
                repo_map,
            )
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
                    failure_context = _attach_repo_map(
                        build_failure_context(
                            final_failures.get("failed_tests", []),
                            cwd or Path.cwd(),
                        ),
                        repo_map,
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
            lowered_task = str(options.task or "").lower()
            failed_tests = final_failures.get("failed_tests", []) if isinstance(final_failures, dict) else []
            first_failure = failed_tests[0] if isinstance(failed_tests, list) and failed_tests else {}
            if (
                isinstance(first_failure, dict)
                and "fix failing tests in " in lowered_task
            ):
                failure_file = str(first_failure.get("file", "") or "").replace("\\", "/")
                if failure_file.startswith("tests/"):
                    patch_plan["task_type"] = "test_generation"
                    patch_plan["target_file"] = failure_file
                    patch_plan["allowed_targets"] = [failure_file]
                    patch_plan["max_deletions"] = 5
                    patch_plan["append_only"] = False
                    patch_plan["failing_test_nodeid"] = str(first_failure.get("test_name", "") or "")
                    patch_plan["failing_test_error"] = str(first_failure.get("error", "") or "")
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
    explicit_patch_command = str(options.command or "").strip().lower() == "patch"
    task_driven_patch_proposal = bool(
        options.propose_patch
        and final_failure_count == 0
        and (explicit_patch_command or is_constructive_task(options.task))
    )
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
        failure_context = _attach_repo_map(
            final_task_context if isinstance(final_task_context, dict) else {"files": []},
            repo_map,
        )

        entrypoint_file = ""
        for item in failure_context.get("files", []) if isinstance(failure_context, dict) else []:
            if isinstance(item, dict):
                path = str(item.get("path", ""))
                if path in {"src/main.py", "main.py", "cli.py", "app.py"}:
                    entrypoint_file = path
                    break
        task_type_hint = classify_task_type(options.task)
        test_task = task_type_hint == "test_generation"
        impl_with_tests_task = task_type_hint in {"implementation_with_tests", "feature_implementation"}
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
            test_constraints = build_patch_constraints(options.task, "test_generation", context=failure_context)
            test_file_hint = str(test_constraints.get("target_file") or _test_hint_path(options.task, failure_context))
            patch_plan["task_type"] = "test_generation"
            patch_plan["target_file"] = test_file_hint
            patch_plan["max_deletions"] = test_constraints.get("max_deletions", 0)
            allowed_targets = test_constraints.get("allowed_targets", [])
            if isinstance(allowed_targets, list) and allowed_targets:
                patch_plan["allowed_targets"] = [str(item) for item in allowed_targets]
            else:
                patch_plan["allowed_targets"] = [test_file_hint] if test_file_hint else ["tests/**"]
            if test_constraints.get("append_only") is not None:
                patch_plan["append_only"] = bool(test_constraints.get("append_only"))
            if test_constraints.get("insertion_hint"):
                patch_plan["insertion_hint"] = str(test_constraints.get("insertion_hint"))
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
            patch_plan["task_type"] = (
                "feature_implementation"
                if task_type_hint == "feature_implementation"
                else "implementation_with_tests"
            )
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
                " Documentation-only scope: modify README.md with usage examples only. "
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

    explicit_scope = options.scope_contract if isinstance(options.scope_contract, dict) else {}
    explicit_scope_active = str(options.command or "").strip().lower() == "patch" and str(explicit_scope.get("source", "")) == "cli_explicit"
    explicit_scope_targets = [_normalize_rel_path(str(item)) for item in explicit_scope.get("allowed_targets", []) if str(item).strip()] if isinstance(explicit_scope.get("allowed_targets", []), list) else []
    explicit_multi_file_patch = bool(
        str(options.command or "").strip().lower() == "patch"
        and explicit_scope_active
        and len(explicit_scope_targets) > 1
    )
    requested_operation = str(options.patch_operation or "").strip().lower()
    if not requested_operation:
        scope_ops_probe = [str(item).strip().lower() for item in explicit_scope.get("allowed_operations", [])] if isinstance(explicit_scope.get("allowed_operations", []), list) else []
        if scope_ops_probe == ["append"]:
            requested_operation = "append"
    if explicit_scope_active:
        scope_targets = [_normalize_rel_path(str(item)) for item in explicit_scope.get("allowed_targets", []) if str(item).strip()] if isinstance(explicit_scope.get("allowed_targets", []), list) else []
        scope_max_files = int(explicit_scope.get("max_files", len(scope_targets)) or len(scope_targets))
        scope_allow_new = bool(explicit_scope.get("allow_new_files", False))
        scope_ops = [str(item) for item in explicit_scope.get("allowed_operations", []) if str(item).strip()] if isinstance(explicit_scope.get("allowed_operations", []), list) else (["create", "replace"] if scope_allow_new else ["replace"])
        scope_missing = [str(item) for item in explicit_scope.get("missing_targets", []) if str(item).strip()] if isinstance(explicit_scope.get("missing_targets", []), list) else []
        patch_plan["allowed_targets"] = scope_targets
        patch_plan["max_files"] = scope_max_files
        patch_plan["allow_new_files"] = scope_allow_new
        patch_plan["allowed_operations"] = scope_ops
        structured_patch["allowed_targets"] = scope_targets
        structured_patch["missing_targets"] = scope_missing
        block_reason = str(explicit_scope.get("block_reason", "") or "").strip() or None
        if block_reason is not None:
            patch_quality = None
            remove_latest_diff(cwd=cwd)
            remove_latest_invalid_diff(cwd=cwd)
            structured_patch["status"] = "failed"
            structured_patch["failure_reason"] = block_reason
            structured_patch["next_actions"] = [
                "use existing files",
                "enable --allow-create",
                "correct file paths",
            ]
            patch_diff.update(
                {
                    "attempted": True,
                    "available": False,
                    "status": "blocked",
                    "path": None,
                    "invalid_diff_path": None,
                    "error": "requested_target_missing",
                    "missing_targets": scope_missing,
                    "preview": "",
                }
            )
            should_attempt_provider_diff = False
            should_patch_flow = False
    if requested_operation == "append":
        explicit_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
        patch_plan["proposed_changes"] = [
            {
                "file": target,
                "change_type": "modify",
                "description": "Append-only update.",
                "reason": "append_operation",
            }
            for target in explicit_targets
        ]
        if len(explicit_targets) != 1:
            patch_quality = None
            remove_latest_diff(cwd=cwd)
            remove_latest_invalid_diff(cwd=cwd)
            patch_diff.update(
                {
                    "attempted": True,
                    "available": False,
                    "status": "blocked",
                    "path": None,
                    "invalid_diff_path": None,
                    "error": "append_requires_single_explicit_file",
                    "preview": "",
                }
            )
            should_attempt_provider_diff = False
            should_patch_flow = False
    baseline_healthy = bool(int(final_failures.get("failure_count", 0) or 0) == 0)
    feature_plan = _build_feature_plan(
        command=str(options.command or ""),
        requested_operation=requested_operation,
        explicit_scope_active=explicit_scope_active,
        explicit_scope=explicit_scope if isinstance(explicit_scope, dict) else {},
        patch_plan=patch_plan if isinstance(patch_plan, dict) else {},
        cwd=(cwd or Path.cwd()).resolve(),
        task_text=str(options.task or ""),
        baseline_healthy=baseline_healthy,
    )
    feature_plan_steps = (
        feature_plan.get("steps", [])
        if isinstance(feature_plan, dict) and isinstance(feature_plan.get("steps", []), list)
        else []
    )
    feature_plan_active = bool(feature_plan_steps)
    disable_docs_wrapped_fallback = bool(explicit_multi_file_patch)
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

    provider_skip_decision = should_skip_provider(options, (cwd or Path.cwd()).resolve())
    if (
        should_attempt_provider_diff
        and provider_enabled
        and should_patch_flow
        and bool(provider_skip_decision.get("skip", False))
    ):
        provider_skipped = True
        skip_reason = str(provider_skip_decision.get("reason", "skipped_provider") or "skipped_provider")
        next_action = (
            str(provider_skip_decision.get("action", "")).strip()
            if provider_skip_decision.get("action") is not None
            else None
        )
        status = "skipped_provider"
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
            "provider": config.providers.provider,
            "model": selected_model,
            "plan_consistent": None,
            "plan_missing_targets": [],
            "path": None,
            "error": skip_reason,
            "preview": "",
            "reason": skip_reason,
        }
        should_attempt_provider_diff = False

    if (
        should_attempt_provider_diff
        and provider_enabled
        and verification.get("available", False)
        and should_patch_flow
        and (has_context_files or has_proposed_changes)
    ):
        aegis_guidance = get_aegis_guidance(
            task=options.task,
            context={
                "aegis": {"enabled": bool(getattr(config.aegis, "enabled", False))},
                "failure_context": failure_context,
                "patch_plan": patch_plan,
            },
            failures=final_failures,
            runtime_policy={"selected_mode": mode},
            timeout_ms=int(getattr(config.aegis, "timeout_ms", 2000) or 2000),
            max_retries=int(getattr(config.aegis, "max_retries", 1) or 1),
        )
        sll_pre_call = run_sll_analysis(str(options.task or ""))
        sll_risk = classify_sll_risk(sll_pre_call)
        task_type = str(patch_plan.get("task_type", "general") or "general")
        test_task = task_type == "test_generation" or is_test_generation_task(options.task)
        impl_with_tests_task = task_type in {"implementation_with_tests", "feature_implementation"}
        docs_task = task_type == "docs_task"
        if impl_with_tests_task:
            allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
            if allowed_targets and isinstance(failure_context.get("files"), list):
                failure_context = _attach_repo_map(
                    {
                    "files": [
                        item
                        for item in failure_context.get("files", [])
                        if isinstance(item, dict) and str(item.get("path", "")).strip() in set(allowed_targets)
                    ]
                    },
                    repo_map,
                )
        if docs_task and isinstance(failure_context.get("files"), list):
            failure_context = _attach_repo_map(
                {
                "files": [
                    item
                    for item in failure_context.get("files", [])
                    if isinstance(item, dict) and str(item.get("path", "")).strip() == "README.md"
                ]
                },
                repo_map,
            )
        failure_context = _attach_relevant_file_snippets(
            context=failure_context if isinstance(failure_context, dict) else {"files": []},
            cwd=(cwd or Path.cwd()).resolve(),
            patch_plan=patch_plan if isinstance(patch_plan, dict) else {},
            repo_map=repo_map if isinstance(repo_map, dict) else {},
        )
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
        provider_result: dict[str, Any]
        use_unified_fallback = True
        structured_blocked = False
        structured_primary_accepted = False
        if bool(options.propose_patch) and (task_type != "docs_task" or feature_plan_active) and requested_operation != "append":
            contract = build_proposal_contract(
                task=options.task,
                patch_plan=patch_plan,
                verification_command=selected_test_command or None,
                stack_hints=detected_capabilities if isinstance(detected_capabilities, dict) else {},
            )
            if feature_plan_active:
                accumulated_diffs: list[str] = []
                touched_files: list[str] = []
                step_errors: list[str] = []
                failure_reason: str | None = None
                blocked_reason_set = {
                    "outside_allowed_targets",
                    "structured_output_invalid",
                    "append_source_conflict",
                    "destructive_docs_rewrite",
                }
                for step in feature_plan_steps:
                    if not isinstance(step, dict):
                        continue
                    step_target = _normalize_rel_path(str(step.get("target_file", "") or ""))
                    if not step_target:
                        structured_blocked = True
                        failure_reason = "structured_output_invalid"
                        break
                    step_operation = str(step.get("operation", "") or "").strip().lower() or "replace"
                    step_patch_plan = deepcopy(patch_plan if isinstance(patch_plan, dict) else {})
                    step_patch_plan["allowed_targets"] = [step_target]
                    step_patch_plan["max_files"] = 1
                    step_patch_plan["task_type"] = "general"
                    allowed_ops = [
                        str(item).strip().lower()
                        for item in contract.allowed_operations
                        if str(item).strip()
                    ]
                    if step_operation in allowed_ops:
                        step_patch_plan["allowed_operations"] = [step_operation]
                    else:
                        step_patch_plan["allowed_operations"] = allowed_ops or ["replace"]
                    step_contract = build_proposal_contract(
                        task=options.task,
                        patch_plan=step_patch_plan,
                        verification_command=selected_test_command or None,
                        stack_hints=detected_capabilities if isinstance(detected_capabilities, dict) else {},
                    )

                    def _attempt_step_structured_edits(override_task: str, step_plan: dict[str, Any] = step_patch_plan) -> dict[str, Any]:
                        result, timed_out = _run_with_provider_heartbeat(
                            options,
                            f"structured patch generation ({step_target})",
                            lambda: generate_structured_edits(
                                provider=config.providers.provider,
                                model=selected_model,
                                task=override_task,
                                failures=final_failures,
                                context=failure_context,
                                patch_plan=step_plan,
                                aegis_execution=aegis_guidance,
                                api_key_env=config.providers.api_key_env,
                                base_url=str(config.providers.base_url or ""),
                                max_context_chars=int(config.patches.max_context_chars),
                            ),
                            timeout_seconds=provider_timeout_seconds,
                        )
                        if timed_out:
                            return {
                                "available": False,
                                "provider": config.providers.provider,
                                "model": selected_model,
                                "text": "",
                                "error": "provider_timeout",
                            }
                        if isinstance(result, dict):
                            return result
                        return {
                            "available": False,
                            "provider": config.providers.provider,
                            "model": selected_model,
                            "text": "",
                            "error": "provider_error",
                        }

                    step_controller = run_structured_proposal_controller(
                        task=options.task,
                        cwd=(cwd or Path.cwd()).resolve(),
                        contract=step_contract,
                        attempt_fn=_attempt_step_structured_edits,
                    )
                    step_reason = str(step_controller.get("failure_reason", "") or "")
                    if not bool(step_controller.get("available", False)):
                        provider_unavailable = step_reason == "provider_unavailable"
                        if provider_unavailable:
                            structured_patch["status"] = "skipped"
                            use_unified_fallback = True
                            structured_blocked = False
                            failure_reason = None
                            accumulated_diffs = []
                            touched_files = []
                            break
                        structured_blocked = True
                        failure_reason = step_reason or "structured_output_invalid"
                        if failure_reason not in blocked_reason_set:
                            failure_reason = "structured_output_invalid"
                        step_errors = [str(item) for item in step_controller.get("errors", [])]
                        structured_patch["retry_attempted"] = bool(step_controller.get("retry_attempted", False))
                        structured_patch["retry_count"] = int(step_controller.get("retry_count", 0) or 0)
                        if isinstance(step_controller.get("target_diagnostics"), dict):
                            structured_patch["target_diagnostics"] = dict(step_controller.get("target_diagnostics", {}))
                        break
                    step_result_obj = step_controller.get("result")
                    if not hasattr(step_result_obj, "diff"):
                        structured_blocked = True
                        failure_reason = "structured_output_invalid"
                        break
                    step_diff = str(getattr(step_result_obj, "diff", "") or "").strip()
                    if not step_diff:
                        structured_blocked = True
                        failure_reason = "structured_output_invalid"
                        break
                    if _is_destructive_docs_rewrite(step_diff, options.task, step_patch_plan if isinstance(step_patch_plan, dict) else {}):
                        structured_blocked = True
                        failure_reason = "destructive_docs_rewrite"
                        break
                    accumulated_diffs.append(step_diff)
                    if hasattr(step_result_obj, "files"):
                        for item in getattr(step_result_obj, "files", []):
                            path = str(item).strip()
                            if path and path not in touched_files:
                                touched_files.append(path)

                if accumulated_diffs:
                    structured_patch["attempted"] = True
                    structured_patch["available"] = True
                    structured_patch["status"] = "accepted"
                    structured_patch["errors"] = []
                    structured_patch["failure_reason"] = None
                    structured_patch["files"] = touched_files
                    structured_primary_accepted = True
                    use_unified_fallback = False
                    provider_result = {
                        "available": True,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "diff": normalize_unified_diff("\n".join(accumulated_diffs)),
                        "error": None,
                    }
                elif structured_blocked:
                    use_unified_fallback = False
                    structured_patch["attempted"] = True
                    structured_patch["available"] = False
                    structured_patch["status"] = "failed"
                    structured_patch["errors"] = step_errors
                    structured_patch["failure_reason"] = failure_reason or "structured_output_invalid"
                    structured_patch["next_actions"] = [
                        "refine task scope",
                        "remove or adjust file constraints",
                        "inspect allowed targets",
                    ]
                    provider_result = {
                        "available": False,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "diff": "",
                        "error": structured_patch["failure_reason"],
                    }
                else:
                    structured_patch["status"] = "skipped"
            else:
                def _attempt_structured_edits(override_task: str) -> dict[str, Any]:
                    result, timed_out = _run_with_provider_heartbeat(
                        options,
                        "structured patch generation",
                        lambda: generate_structured_edits(
                            provider=config.providers.provider,
                            model=selected_model,
                            task=override_task,
                            failures=final_failures,
                            context=failure_context,
                            patch_plan=patch_plan,
                            aegis_execution=aegis_guidance,
                            api_key_env=config.providers.api_key_env,
                            base_url=str(config.providers.base_url or ""),
                            max_context_chars=int(config.patches.max_context_chars),
                        ),
                        timeout_seconds=provider_timeout_seconds,
                    )
                    if timed_out:
                        return {
                            "available": False,
                            "provider": config.providers.provider,
                            "model": selected_model,
                            "text": "",
                            "error": "provider_timeout",
                        }
                    if isinstance(result, dict):
                        return result
                    return {
                        "available": False,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "text": "",
                        "error": "provider_error",
                    }

                controller = run_structured_proposal_controller(
                    task=options.task,
                    cwd=(cwd or Path.cwd()).resolve(),
                    contract=contract,
                    attempt_fn=_attempt_structured_edits,
                )
                structured_patch["attempted"] = bool(controller.get("attempted", False))
                structured_patch["status"] = str(controller.get("status", "skipped"))
                structured_patch["errors"] = [str(item) for item in controller.get("errors", [])]
                structured_patch["failure_reason"] = controller.get("failure_reason")
                structured_patch["retry_attempted"] = bool(controller.get("retry_attempted", False))
                structured_patch["retry_count"] = int(controller.get("retry_count", 0) or 0)
                if isinstance(controller.get("target_diagnostics"), dict):
                    structured_patch["target_diagnostics"] = dict(controller.get("target_diagnostics", {}))
                result_obj = controller.get("result")
                if hasattr(result_obj, "files"):
                    structured_patch["files"] = [str(item) for item in getattr(result_obj, "files", [])]
                if bool(controller.get("available", False)) and hasattr(result_obj, "diff"):
                    structured_patch["available"] = True
                    structured_patch["status"] = "accepted"
                    structured_primary_accepted = True
                    use_unified_fallback = False
                    provider_result = {
                        "available": True,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "diff": str(getattr(result_obj, "diff", "") or ""),
                        "error": None,
                    }
                else:
                    provider_unavailable = str(controller.get("failure_reason", "")) == "provider_unavailable"
                    if provider_unavailable:
                        structured_patch["status"] = "skipped"
                        use_unified_fallback = True
                    else:
                        structured_blocked = True
                        use_unified_fallback = False
                        structured_patch["status"] = "failed"
                        structured_patch["next_actions"] = [
                            "refine task scope",
                            "remove or adjust file constraints",
                            "inspect allowed targets",
                        ]
                        provider_result = {
                            "available": False,
                            "provider": config.providers.provider,
                            "model": selected_model,
                            "diff": "",
                            "error": "structured_output_invalid",
                        }
        if requested_operation == "append":
            append_target = ""
            if isinstance(patch_plan.get("allowed_targets", []), list) and patch_plan.get("allowed_targets", []):
                append_target = str(patch_plan.get("allowed_targets", [])[0]).strip()
            append_prompt_context = dict(failure_context) if isinstance(failure_context, dict) else {"files": []}
            append_target_contexts: list[dict[str, Any]] = []
            if append_target:
                target_file = ((cwd or Path.cwd()).resolve() / append_target).resolve()
                if target_file.exists() and target_file.is_file():
                    original_text_for_context = target_file.read_text(encoding="utf-8", errors="replace")
                    append_target_contexts.append(
                        _build_append_target_context(
                            cwd=(cwd or Path.cwd()).resolve(),
                            target_path=append_target,
                            original_text=original_text_for_context,
                        )
                    )
            append_prompt_context["append_target_contexts"] = append_target_contexts
            append_result, append_timed_out = _run_with_provider_heartbeat(
                options,
                "append content generation",
                lambda: generate_structured_edits(
                    provider=config.providers.provider,
                    model=selected_model,
                    task=options.task,
                    failures=final_failures,
                    context=append_prompt_context,
                    patch_plan=patch_plan,
                    aegis_execution=aegis_guidance,
                    api_key_env=config.providers.api_key_env,
                    base_url=str(config.providers.base_url or ""),
                    max_context_chars=int(config.patches.max_context_chars),
                    operation="append",
                ),
                timeout_seconds=provider_timeout_seconds,
            )
            if append_timed_out:
                provider_result = {
                    "available": False,
                    "provider": config.providers.provider,
                    "model": selected_model,
                    "diff": "",
                    "error": "provider_timeout",
                }
            elif not isinstance(append_result, dict) or not bool(append_result.get("available", False)):
                provider_result = {
                    "available": False,
                    "provider": config.providers.provider,
                    "model": selected_model,
                    "diff": "",
                    "error": str((append_result or {}).get("error", "provider_error")) if isinstance(append_result, dict) else "provider_error",
                }
            else:
                append_text = str(append_result.get("text", "") or "")
                append_ok, append_content, append_parse_error = _parse_append_provider_response(append_text)
                if not append_ok or append_content is None:
                    structured_blocked = True
                    structured_patch["status"] = "failed"
                    structured_patch["failure_reason"] = append_parse_error or "append_output_invalid"
                    provider_result = {
                        "available": False,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "diff": "",
                        "error": append_parse_error or "append_output_invalid",
                    }
                elif append_content == "":
                    structured_blocked = True
                    structured_patch["status"] = "failed"
                    structured_patch["failure_reason"] = "no_append_needed"
                    provider_result = {
                        "available": False,
                        "provider": config.providers.provider,
                        "model": selected_model,
                        "diff": "",
                        "error": "no_append_needed",
                    }
                else:
                    target_file = ((cwd or Path.cwd()).resolve() / append_target).resolve()
                    if not target_file.exists() or not target_file.is_file():
                        provider_result = {"available": False, "provider": config.providers.provider, "model": selected_model, "diff": "", "error": "requested_target_missing"}
                    else:
                        original_text = target_file.read_text(encoding="utf-8", errors="replace")
                        append_sanity_error = _append_python_sanity_error(
                            target_path=append_target,
                            original_text=original_text,
                            appended_content=append_content,
                        )
                        if append_sanity_error:
                            structured_blocked = True
                            structured_patch["status"] = "failed"
                            structured_patch["failure_reason"] = append_sanity_error
                            provider_result = {
                                "available": False,
                                "provider": config.providers.provider,
                                "model": selected_model,
                                "diff": "",
                                "error": append_sanity_error,
                            }
                        else:
                            append_source_conflict = _append_source_conflict_error(
                                cwd=(cwd or Path.cwd()).resolve(),
                                target_path=append_target,
                                appended_content=append_content,
                                relevant_file_snippets=append_prompt_context.get("relevant_file_snippets", [])
                                if isinstance(append_prompt_context.get("relevant_file_snippets", []), list)
                                else [],
                            )
                            if append_source_conflict:
                                structured_blocked = True
                                structured_patch["status"] = "failed"
                                structured_patch["failure_reason"] = append_source_conflict
                                provider_result = {
                                    "available": False,
                                    "provider": config.providers.provider,
                                    "model": selected_model,
                                    "diff": "",
                                    "error": append_source_conflict,
                                }
                            else:
                                append_diff = _build_append_diff(target_path=append_target, original_text=original_text, appended_content=append_content)
                                ok_append, append_error = _validate_append_diff(
                                    diff_text=append_diff,
                                    original_text=original_text,
                                    target_path=append_target,
                                    cwd=(cwd or Path.cwd()),
                                )
                                provider_result = {
                                    "available": bool(ok_append and append_diff),
                                    "provider": config.providers.provider,
                                    "model": selected_model,
                                    "diff": append_diff if ok_append else "",
                                    "error": append_error if not ok_append else None,
                                }
            use_unified_fallback = False
        if use_unified_fallback:
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
                    aegis_execution=aegis_guidance,
                    api_key_env=config.providers.api_key_env,
                    base_url=str(config.providers.base_url or ""),
                    sll_guidance=None,
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
            if bool(options.propose_patch) and (
                structured_patch.get("attempted", False) or str(structured_patch.get("status", "")) == "skipped"
            ):
                structured_patch["fallback"] = "unified_diff"
        initial_diff = normalize_unified_diff(str(provider_result.get("diff", "") or "").strip()).strip()
        sll_post_call = run_sll_analysis(initial_diff)
        sll_risk = classify_sll_risk(sll_post_call)
        if int(final_failures.get("failure_count", 0) or 0) > 0:
            sll_fix_guidance = build_sll_fix_guidance(sll_post_call)
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
        early_content_invalid_reason = _hard_invalid_content_reason(
            diff_text=initial_diff,
            validation=validation_result if isinstance(validation_result, dict) else {},
            test_task=test_task,
            task_text=options.task,
        )
        if early_content_invalid_reason:
            repair_result = {
                "applied": False,
                "status": "skipped",
                "reason": early_content_invalid_reason,
                "diff": initial_diff,
                "error": None,
                "repair_file_count": 0,
                "raw_repair_file_count": 0,
                "repair_targets": [],
            }
        if not bool(validation_result.get("valid", False)) and (initial_diff or docs_task):
            if docs_task and not disable_docs_wrapped_fallback:
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
            if not early_content_invalid_reason:
                _progress(options, "attempting repair")
            if not bool(repair_result.get("applied", False)) and not early_content_invalid_reason:
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
                    diff_text=initial_diff,
                    validation=validation_result,
                    test_task=test_task,
                    task_text=options.task,
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
        if requested_operation == "append":
            regenerate = False
            reasons = []
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

        if regenerate and not structured_blocked and not structured_primary_accepted:
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
                test_constraints = build_patch_constraints(options.task, "test_generation", context=failure_context)
                regen_instructions = test_constraints.get("regeneration_instructions", [])
                if isinstance(regen_instructions, list):
                    enhanced_constraints.extend(str(item) for item in regen_instructions)
                if not explicit_scope_active:
                    allowed_targets = test_constraints.get("allowed_targets", [])
                    if isinstance(allowed_targets, list) and allowed_targets:
                        enhanced_patch_plan["allowed_targets"] = [str(item) for item in allowed_targets]
                    else:
                        enhanced_patch_plan["allowed_targets"] = [
                            path for path in _extract_context_paths(failure_context) if path.startswith("tests/")
                        ]
            if impl_with_tests_task:
                planned_targets = sorted(_collect_plan_targets(patch_plan))
                if planned_targets and not explicit_scope_active:
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
                    if (not explicit_scope_active) and isinstance(corrective.get("allowed_targets"), list) and corrective.get("allowed_targets"):
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
                    aegis_execution=aegis_guidance,
                    api_key_env=config.providers.api_key_env,
                    base_url=str(config.providers.base_url or ""),
                    sll_guidance=sll_fix_guidance,
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
            if docs_task and not disable_docs_wrapped_fallback and second_diff and not bool(second_validation.get("valid", False)):
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
                diff_text=second_diff,
                validation=second_validation,
                test_task=test_task,
                task_text=options.task,
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
        if feature_plan_active and bool(validation_used.get("valid", False)):
            planned_step_targets = {
                _normalize_rel_path(str(item.get("target_file", "") or ""))
                for item in feature_plan_steps
                if isinstance(item, dict) and str(item.get("target_file", "")).strip()
            }
            diff_targets = _collect_diff_targets(validation_used if isinstance(validation_used, dict) else {})
            if planned_step_targets:
                missing_step_targets = sorted(path for path in planned_step_targets if path not in diff_targets)
                plan_consistent = not missing_step_targets
                plan_missing_targets = missing_step_targets
        if requested_operation == "append" and bool(validation_used.get("valid", False)):
            allowed = {
                _normalize_rel_path(str(item))
                for item in patch_plan.get("allowed_targets", [])
                if str(item).strip()
            } if isinstance(patch_plan.get("allowed_targets", []), list) else set()
            diff_targets = _collect_diff_targets(validation_used if isinstance(validation_used, dict) else {})
            if allowed and diff_targets and diff_targets.issubset(allowed):
                plan_consistent = True
                plan_missing_targets = []
        if provider_used.get("available", False) and diff_text and bool(validation_used.get("valid", False)):
            _progress(options, "checking syntax of proposed Python changes")
            syntactic_valid, syntactic_error = _syntactic_python_check(diff_text, cwd=(cwd or Path.cwd()))
            additions = int((validation_used.get("summary", {}) or {}).get("additions", 0))
            size_threshold = 500 if test_task else 800
            content_hard_invalid = _hard_invalid_content_reason(
                diff_text=diff_text,
                validation=validation_used if isinstance(validation_used, dict) else {},
                test_task=test_task,
                task_text=options.task,
            )
            if content_hard_invalid is None and _is_destructive_docs_rewrite(diff_text, options.task, patch_plan if isinstance(patch_plan, dict) else {}):
                content_hard_invalid = "destructive_docs_rewrite"
            if content_hard_invalid is None and _is_destructive_source_rewrite(diff_text, options.task, patch_plan if isinstance(patch_plan, dict) else {}):
                content_hard_invalid = "destructive_source_rewrite"
            if content_hard_invalid:
                patch_quality = None
                invalid_path = str(write_latest_invalid_diff(diff_text, cwd=cwd))
                remove_latest_diff(cwd=cwd)
                syntactic_error = None
                syntactic_valid = True
            elif syntactic_valid is False:
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
            content_hard_invalid = _hard_invalid_content_reason(
                diff_text=diff_text,
                validation=validation_used if isinstance(validation_used, dict) else {},
                test_task=test_task,
                task_text=options.task,
            )
            if content_hard_invalid is None and _is_destructive_docs_rewrite(diff_text, options.task, patch_plan if isinstance(patch_plan, dict) else {}):
                content_hard_invalid = "destructive_docs_rewrite"
            if content_hard_invalid is None and _is_destructive_source_rewrite(diff_text, options.task, patch_plan if isinstance(patch_plan, dict) else {}):
                content_hard_invalid = "destructive_source_rewrite"
            if content_hard_invalid:
                patch_diff["error"] = content_hard_invalid
            elif syntactic_valid is False:
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
            and requested_operation != "append"
            and not bool(regeneration.get("attempted", False))
            and not structured_blocked
            and not structured_primary_accepted
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
            if planned_targets and not explicit_scope_active:
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
                        if (not explicit_scope_active) and isinstance(allowed, list) and allowed:
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
                    aegis_execution=aegis_guidance,
                    api_key_env=config.providers.api_key_env,
                    base_url=str(config.providers.base_url or ""),
                    sll_guidance=sll_fix_guidance,
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
            if docs_task and not disable_docs_wrapped_fallback and second_diff and not bool(second_validation.get("valid", False)):
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
                diff_text=second_diff,
                validation=second_validation,
                test_task=test_task,
                task_text=options.task,
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
        if structured_blocked:
            remove_latest_diff(cwd=cwd)
            remove_latest_invalid_diff(cwd=cwd)
            patch_quality = None
            blocked_error = (
                str(structured_patch.get("failure_reason", "") or "append_output_invalid")
                if requested_operation == "append"
                else (
                    str(structured_patch.get("failure_reason", "") or "structured_output_invalid")
                    if feature_plan_active
                    else "structured_output_invalid"
                )
            )
            patch_diff.update(
                {
                    "attempted": True,
                    "available": False,
                    "status": "blocked",
                    "path": None,
                    "invalid_diff_path": None,
                    "error": blocked_error,
                    "preview": "",
                }
            )
            if str(structured_patch.get("failure_reason", "") or "") == "outside_allowed_targets":
                diagnostics = structured_patch.get("target_diagnostics")
                if isinstance(diagnostics, dict):
                    patch_diff["target_diagnostics"] = diagnostics
            if requested_operation == "append":
                patch_diff["plan_consistent"] = None
                patch_diff["plan_missing_targets"] = []
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
        patch_diff["error"] = _prioritize_patch_error(
            current_error=str(patch_diff.get("error", "") or "") or None,
            patch_plan=patch_plan if isinstance(patch_plan, dict) else {},
            structured_patch=structured_patch if isinstance(structured_patch, dict) else {},
            task_text=options.task,
            requested_operation=requested_operation,
        )
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

    if isinstance(patch_diff, dict):
        validation_for_touched = patch_diff.get("validation_result", {}) if isinstance(patch_diff.get("validation_result", {}), dict) else {}
        patch_diff["touched_files"] = sorted(_collect_diff_targets(validation_for_touched))

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
    if (
        bool(options.propose_patch)
        and bool(patch_diff_payload.get("attempted", False))
        and not bool(patch_diff_payload.get("available", False))
        and bool(str(patch_diff_payload.get("error", "") or "").strip())
        and "tests_passed" in str(status or "")
    ):
        status = "completed_provider_unavailable"

    operation_source = "unknown"
    if requested_operation:
        if str(options.patch_operation or "").strip():
            operation_source = "cli"
        elif explicit_scope_active:
            operation_source = "cli"
    verification_diagnostics: dict[str, Any] | None = None
    if explicit_multi_file_patch and int(final_failures.get("failure_count", 0) or 0) > 0:
        last_cmd = commands_run[-1] if commands_run and isinstance(commands_run[-1], dict) else {}
        full_output = str(last_cmd.get("full_output", "") or "")
        verification_diagnostics = {
            "command": str(last_cmd.get("command", "") or verification.get("command") or ""),
            "status": str(last_cmd.get("status", "") or ""),
            "exit_code": last_cmd.get("exit_code"),
            "output": full_output,
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
        "repo_map": repo_map,
        "commands_run": commands_run,
        "test_attempts": test_attempts,
        "initial_failures": initial_failures,
        "final_failures": final_failures,
        "symptoms": symptoms,
        "retry_policy": retry_policy,
        "failures": failures,
        "failure_context": failure_context,
        "sll_analysis": sll_analysis,
        "sll_pre_call": sll_pre_call,
        "sll_post_call": sll_post_call,
        "sll_risk": sll_risk,
        "sll_fix_guidance": sll_fix_guidance,
        "patch_plan": patch_plan,
        "patch_diff": patch_diff,
        "structured_patch": structured_patch,
        "patch_quality": patch_quality,
        "patch_operation": (
            {
                "operation": requested_operation,
                "source": operation_source,
            }
            if requested_operation
            else None
        ),
        "feature_plan": feature_plan,
        "apply_safety": apply_safety,
        "verification": verification,
        "verification_diagnostics": verification_diagnostics,
        "aegis_guidance": aegis_guidance,
        "provider_skipped": provider_skipped,
        "skip_reason": skip_reason or None,
        "next_action": next_action,
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
    patch_diff_payload = payload.get("patch_diff", {}) if isinstance(payload.get("patch_diff"), dict) else {}
    diff_path = str(patch_diff_payload.get("path", "") or "").strip()
    if diff_path:
        try:
            diff_text_for_sll = Path(diff_path).read_text(encoding="utf-8", errors="replace")
            patch_safety = safety_report_to_dict(scan_diff(diff_text_for_sll))
            payload["patch_safety"] = patch_safety
            payload["sll_post_call"] = run_sll_analysis(diff_text_for_sll)
            payload["sll_risk"] = classify_sll_risk(payload["sll_post_call"])
            if int((payload.get("final_failures", {}) if isinstance(payload.get("final_failures", {}), dict) else {}).get("failure_count", 0) or 0) > 0:
                payload["sll_fix_guidance"] = build_sll_fix_guidance(payload["sll_post_call"])
        except Exception:
            pass
    if "patch_safety" not in payload:
        payload["patch_safety"] = patch_safety or {"highest_severity": "pass", "issues": []}
    if int((payload.get("final_failures", {}) if isinstance(payload.get("final_failures", {}), dict) else {}).get("failure_count", 0) or 0) > 0:
        payload["impact"] = _build_impact_payload(
            commands_run=commands_run,
            final_failures=final_failures if isinstance(final_failures, dict) else {},
            patch_diff=patch_diff if isinstance(patch_diff, dict) else {},
            structured_patch=structured_patch if isinstance(structured_patch, dict) else {},
            patch_plan=patch_plan if isinstance(patch_plan, dict) else {},
            failure_context=failure_context if isinstance(failure_context, dict) else {},
            task=options.task,
        )
    return payload


def _collect_changed_files(patch_diff: dict[str, Any], structured_patch: dict[str, Any], patch_plan: dict[str, Any]) -> list[str]:
    _ = structured_patch
    _ = patch_plan
    validation = patch_diff.get("validation_result", {}) if isinstance(patch_diff.get("validation_result", {}), dict) else {}
    targets = _collect_diff_targets(validation)
    return sorted(targets)


def _collect_repo_file_candidates(failure_context: dict[str, Any], patch_plan: dict[str, Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in failure_context.get("files", []) if isinstance(failure_context.get("files", []), list) else []:
        path_value = str(item.get("path", "") if isinstance(item, dict) else "").strip().replace("\\", "/")
        if path_value and path_value not in seen:
            seen.add(path_value)
            out.append(path_value)
    allowed = patch_plan.get("allowed_targets", []) if isinstance(patch_plan.get("allowed_targets", []), list) else []
    for item in allowed:
        path_value = str(item).strip().replace("\\", "/")
        if path_value and path_value not in seen:
            seen.add(path_value)
            out.append(path_value)
    return out


def _build_impact_payload(
    *,
    commands_run: list[dict[str, Any]],
    final_failures: dict[str, Any],
    patch_diff: dict[str, Any],
    structured_patch: dict[str, Any],
    patch_plan: dict[str, Any],
    failure_context: dict[str, Any],
    task: str,
) -> dict[str, object]:
    raw_output = ""
    exit_code: int | None = None
    for item in reversed(commands_run):
        full_output = str(item.get("full_output", "") or "")
        if full_output.strip():
            raw_output = full_output
            maybe_exit = item.get("exit_code")
            exit_code = int(maybe_exit) if isinstance(maybe_exit, int) else None
            break
    if not raw_output:
        failed_tests = final_failures.get("failed_tests", []) if isinstance(final_failures.get("failed_tests", []), list) else []
        raw_output = "\n".join(str(item.get("error", "")) for item in failed_tests if isinstance(item, dict) and str(item.get("error", "")).strip())
    changed_files = _collect_changed_files(patch_diff, structured_patch, patch_plan)
    repo_files = _collect_repo_file_candidates(failure_context, patch_plan)
    signals = extract_failure_signals(
        raw_output=raw_output,
        exit_code=exit_code,
        changed_files=changed_files,
        repo_files=repo_files,
    )
    report = resolve_impact(signals=signals, changed_files=changed_files, repo_files=repo_files, task=task)
    return impact_report_to_dict(report)


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
