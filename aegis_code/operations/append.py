from __future__ import annotations

import ast
import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.operations.errors import (
    APPEND_OUTPUT_INVALID,
    APPEND_SEMANTIC_SUSPICIOUS,
    APPEND_SYNTAX_INVALID,
    INVALID_APPEND_OPERATION,
    NO_APPEND_NEEDED,
)
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.runtime_components.append_context import _build_append_target_context
from aegis_code.runtime_components.semantic_guards import _append_source_conflict_error

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


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
        return APPEND_SYNTAX_INVALID
    try:
        appended_tree = ast.parse(str(appended_content or ""))
    except SyntaxError:
        return APPEND_SYNTAX_INVALID
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
        if len(name) == 1 and name not in defined_names and name not in builtins_names:
            suspicious.add(name)
    if suspicious:
        return APPEND_SEMANTIC_SUSPICIOUS
    return None


def _parse_append_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, APPEND_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, APPEND_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, APPEND_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, APPEND_OUTPUT_INVALID
    if "changes" in payload:
        return False, None, APPEND_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, APPEND_OUTPUT_INVALID
    if not content.strip():
        return True, "", None
    normalized = content if content.endswith("\n") else f"{content}\n"
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, APPEND_OUTPUT_INVALID
    return True, normalized, None


def _validate_append_diff(*, diff_text: str, original_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    _ = original_text
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, INVALID_APPEND_OPERATION
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) != 0:
        return False, INVALID_APPEND_OPERATION
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, INVALID_APPEND_OPERATION
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    new_path = str(file_entry.get("new_path", "") or "")
    if new_path != target_path:
        return False, INVALID_APPEND_OPERATION
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, INVALID_APPEND_OPERATION
    return True, None


def run_append_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    context = request.context if isinstance(request.context, dict) else {}
    provider = str(context.get("provider", "") or "")
    model = str(request.model or context.get("model", "") or "")
    run_with_provider_heartbeat = context.get("run_with_provider_heartbeat")
    generate_structured_edits_fn = context.get("generate_structured_edits")
    task_options = context.get("task_options")
    timeout_seconds = int(request.provider_timeout or 60)
    if not callable(run_with_provider_heartbeat) or not callable(generate_structured_edits_fn):
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="provider_error",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    target_path = str(request.contract.target_file or "").strip()
    failure_context = context.get("failure_context")
    append_prompt_context = dict(failure_context) if isinstance(failure_context, dict) else {"files": []}
    append_target_contexts: list[dict[str, Any]] = []
    if target_path:
        target_file = (request.cwd.resolve() / target_path).resolve()
        if target_file.exists() and target_file.is_file():
            original_text_for_context = target_file.read_text(encoding="utf-8", errors="replace")
            append_target_contexts.append(
                _build_append_target_context(
                    cwd=request.cwd.resolve(),
                    target_path=target_path,
                    original_text=original_text_for_context,
                )
            )
    append_prompt_context["append_target_contexts"] = append_target_contexts

    append_result, append_timed_out = run_with_provider_heartbeat(
        task_options,
        "append content generation",
        lambda: generate_structured_edits_fn(
            provider=provider,
            model=model,
            task=request.task,
            failures=request.failures,
            context=append_prompt_context,
            patch_plan=request.patch_plan,
            aegis_execution=request.aegis_execution,
            api_key_env=context.get("api_key_env"),
            base_url=str(context.get("base_url", "") or ""),
            max_context_chars=int(context.get("max_context_chars", 0) or 0),
            operation="append",
        ),
        timeout_seconds=timeout_seconds,
    )
    if append_timed_out:
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="provider_timeout",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if not isinstance(append_result, dict) or not bool(append_result.get("available", False)):
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=str((append_result or {}).get("error", "provider_error")) if isinstance(append_result, dict) else "provider_error",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    append_text = str(append_result.get("text", "") or "")
    append_ok, append_content, append_parse_error = _parse_append_provider_response(append_text)
    if not append_ok or append_content is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=append_parse_error or APPEND_OUTPUT_INVALID,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if append_content == "":
        return OperationResult(
            attempted=True,
            status="blocked",
            error=NO_APPEND_NEEDED,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    target_file = (request.cwd.resolve() / target_path).resolve()
    if not target_file.exists() or not target_file.is_file():
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="requested_target_missing",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    original_text = target_file.read_text(encoding="utf-8", errors="replace")
    append_sanity_fn = context.get("append_python_sanity_error")
    if not callable(append_sanity_fn):
        append_sanity_fn = _append_python_sanity_error
    append_sanity_error = append_sanity_fn(
        target_path=target_path,
        original_text=original_text,
        appended_content=append_content,
    )
    if append_sanity_error:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=append_sanity_error,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    append_source_conflict = _append_source_conflict_error(
        cwd=request.cwd.resolve(),
        target_path=target_path,
        appended_content=append_content,
        relevant_file_snippets=append_prompt_context.get("relevant_file_snippets", [])
        if isinstance(append_prompt_context.get("relevant_file_snippets", []), list)
        else [],
    )
    if append_source_conflict:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=append_source_conflict,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    append_diff = _build_append_diff(target_path=target_path, original_text=original_text, appended_content=append_content)
    validate_append_fn = context.get("validate_append_diff")
    if not callable(validate_append_fn):
        validate_append_fn = _validate_append_diff
    ok_append, append_error = validate_append_fn(
        diff_text=append_diff,
        original_text=original_text,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok_append or not append_diff:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=append_error,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    return OperationResult(
        attempted=True,
        status="generated",
        diff_text=append_diff,
        error=None,
        provider=provider or None,
        model=model or None,
        operation=request.contract.operation,
        source=request.contract.source,
    )
