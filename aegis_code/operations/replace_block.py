from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.operations.errors import (
    OPERATION_ANCHOR_AMBIGUOUS,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_CONTRACT_INVALID,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
    REPLACE_BLOCK_OUTPUT_INVALID,
)
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _normalize_line_endings(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def resolve_replace_block_span(
    *,
    original_text: str,
    anchor: str,
) -> tuple[bool, tuple[int, int] | None, str | None]:
    haystack = _normalize_line_endings(original_text)
    needle = _normalize_line_endings(anchor)
    if not needle:
        return False, None, OPERATION_CONTRACT_INVALID
    matches: list[int] = []
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            break
        matches.append(index)
        start = index + 1
    if not matches:
        return False, None, OPERATION_ANCHOR_NOT_FOUND
    if len(matches) != 1:
        return False, None, OPERATION_ANCHOR_AMBIGUOUS
    first = int(matches[0])
    return True, (first, first + len(needle)), None


def replace_block_span(
    *,
    original_text: str,
    span: tuple[int, int],
    replacement_content: str,
) -> str:
    start, end = int(span[0]), int(span[1])
    return str(original_text or "")[:start] + str(replacement_content or "") + str(original_text or "")[end:]


def _parse_replace_block_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    if not content.strip():
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    if any(marker in content for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, REPLACE_BLOCK_OUTPUT_INVALID
    return True, content, None


def _build_replace_block_diff(*, target_path: str, original_text: str, new_text: str) -> str:
    old_lines = str(original_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _validate_replace_block_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, OPERATION_VALIDATION_FAILED
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("additions", 0) or 0) + int(summary.get("deletions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, OPERATION_VALIDATION_FAILED
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    old_path = file_entry.get("old_path")
    new_path = file_entry.get("new_path")
    if old_path is None or new_path is None:
        return False, OPERATION_VALIDATION_FAILED
    if str(old_path) != target_path or str(new_path) != target_path:
        return False, OPERATION_VALIDATION_FAILED
    return True, None


def run_replace_block_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    context = request.context if isinstance(request.context, dict) else {}
    deps = request.dependencies
    provider = str(context.get("provider", "") or "")
    model = str(request.model or context.get("model", "") or "")
    run_with_provider_heartbeat = (
        deps.run_with_provider_heartbeat
        if deps and deps.run_with_provider_heartbeat
        else context.get("run_with_provider_heartbeat")
    )
    generate_text_fn = deps.generate_text if deps and deps.generate_text else context.get("generate_text")
    build_prompt_fn = (
        deps.build_replace_block_prompt
        if deps and deps.build_replace_block_prompt
        else context.get("build_replace_block_prompt")
    )
    task_options = deps.task_options if deps and deps.task_options is not None else context.get("task_options")
    timeout_seconds = int(request.provider_timeout or 60)
    if not callable(run_with_provider_heartbeat) or not callable(generate_text_fn) or not callable(build_prompt_fn):
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
    anchor = str(request.contract.anchor or "").strip()
    if not target_path or not anchor:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=OPERATION_CONTRACT_INVALID,
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
            error=OPERATION_TARGET_MISSING,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    original_text = _normalize_line_endings(
        str(context.get("replace_original_text"))
        if context.get("replace_original_text") is not None
        else target_file.read_text(encoding="utf-8", errors="replace")
    )
    span_value = context.get("replace_anchor_span")
    resolved_span: tuple[int, int] | None = None
    if (
        isinstance(span_value, (tuple, list))
        and len(span_value) == 2
        and isinstance(span_value[0], int)
        and isinstance(span_value[1], int)
    ):
        resolved_span = (int(span_value[0]), int(span_value[1]))
    if resolved_span is None:
        span_ok, span, span_error = resolve_replace_block_span(original_text=original_text, anchor=anchor)
        if not span_ok or span is None:
            return OperationResult(
                attempted=True,
                status="blocked",
                error=span_error or OPERATION_CONTRACT_INVALID,
                provider=provider or None,
                model=model or None,
                operation=request.contract.operation,
                source=request.contract.source,
            )
        resolved_span = span

    prompt = build_prompt_fn(
        task=request.task,
        target_path=target_path,
        anchor=anchor,
        failure_context=context.get("failure_context") if isinstance(context.get("failure_context"), dict) else {"files": []},
        patch_plan=request.patch_plan if isinstance(request.patch_plan, dict) else {},
    )
    replace_result, replace_timed_out = run_with_provider_heartbeat(
        task_options,
        "replace-block content generation",
        lambda: generate_text_fn(
            provider=provider,
            model=model,
            prompt=prompt,
            api_key_env=(deps.api_key_env if deps and deps.api_key_env is not None else context.get("api_key_env")),
            base_url=str(
                (deps.base_url if deps and deps.base_url is not None else context.get("base_url", ""))
                or ""
            ),
        ),
        timeout_seconds=timeout_seconds,
    )
    if replace_timed_out:
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="provider_timeout",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if not isinstance(replace_result, dict) or not bool(replace_result.get("available", False)):
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=str((replace_result or {}).get("error", "provider_error")) if isinstance(replace_result, dict) else "provider_error",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    replace_text = str(replace_result.get("text", "") or "")
    replace_ok, replacement_content, replace_parse_error = _parse_replace_block_provider_response(replace_text)
    if not replace_ok or replacement_content is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=replace_parse_error or REPLACE_BLOCK_OUTPUT_INVALID,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    replaced_text = replace_block_span(
        original_text=original_text,
        span=resolved_span,
        replacement_content=replacement_content,
    )
    replace_diff = _build_replace_block_diff(
        target_path=target_path,
        original_text=original_text,
        new_text=replaced_text,
    )
    ok_replace, validate_error = _validate_replace_block_diff(
        diff_text=replace_diff,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok_replace or not replace_diff:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=validate_error,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    return OperationResult(
        attempted=True,
        status="generated",
        diff_text=replace_diff,
        error=None,
        provider=provider or None,
        model=model or None,
        operation=request.contract.operation,
        source=request.contract.source,
    )
