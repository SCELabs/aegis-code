from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.operations.errors import (
    INSERT_OUTPUT_INVALID,
    OPERATION_ANCHOR_AMBIGUOUS,
    OPERATION_ANCHOR_NOT_FOUND,
    OPERATION_CONTRACT_INVALID,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
)
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _parse_insert_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, INSERT_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, INSERT_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, INSERT_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, INSERT_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, INSERT_OUTPUT_INVALID
    normalized = content if content.endswith("\n") else f"{content}\n"
    if not normalized.strip():
        return False, None, INSERT_OUTPUT_INVALID
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, INSERT_OUTPUT_INVALID
    return True, normalized, None


def _insert_after_anchor(*, original_text: str, anchor: str, insert_content: str) -> tuple[bool, str | None, str | None]:
    ok, index, error = resolve_insert_after_index(original_text=original_text, anchor=anchor)
    if not ok or index is None:
        return False, None, error
    new_text = insert_after_index(original_text=original_text, index=index, insert_content=insert_content)
    return True, new_text, None


def resolve_insert_after_index(*, original_text: str, anchor: str) -> tuple[bool, int | None, str | None]:
    lines = str(original_text or "").splitlines(keepends=True)
    needle = str(anchor or "").strip()
    matches = [idx for idx, line in enumerate(lines) if str(line).rstrip("\n\r").strip() == needle]
    if not matches:
        return False, None, OPERATION_ANCHOR_NOT_FOUND
    if len(matches) != 1:
        return False, None, OPERATION_ANCHOR_AMBIGUOUS
    return True, int(matches[0]), None


def insert_after_index(*, original_text: str, index: int, insert_content: str) -> str:
    lines = str(original_text or "").splitlines(keepends=True)
    idx = int(index)
    insertion = str(insert_content or "")
    new_lines = lines[: idx + 1] + [insertion] + lines[idx + 1 :]
    return "".join(new_lines)


def _build_insert_after_diff(*, target_path: str, original_text: str, new_text: str) -> str:
    old_lines = str(original_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _validate_insert_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
    inspected = inspect_diff(diff_text, cwd=cwd)
    if not bool(inspected.get("valid", False)):
        return False, OPERATION_VALIDATION_FAILED
    summary = inspected.get("summary", {}) if isinstance(inspected.get("summary"), dict) else {}
    if int(summary.get("deletions", 0) or 0) != 0:
        return False, OPERATION_VALIDATION_FAILED
    files = inspected.get("files", []) if isinstance(inspected.get("files"), list) else []
    if len(files) != 1:
        return False, OPERATION_VALIDATION_FAILED
    file_entry = files[0] if files and isinstance(files[0], dict) else {}
    new_path = str(file_entry.get("new_path", "") or "")
    if new_path != target_path:
        return False, OPERATION_VALIDATION_FAILED
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    return True, None


def run_insert_after_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    context = request.context if isinstance(request.context, dict) else {}
    provider = str(context.get("provider", "") or "")
    model = str(request.model or context.get("model", "") or "")
    run_with_provider_heartbeat = context.get("run_with_provider_heartbeat")
    generate_text_fn = context.get("generate_text")
    build_prompt_fn = context.get("build_insert_after_prompt")
    task_options = context.get("task_options")
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
    prompt = build_prompt_fn(
        task=request.task,
        target_path=target_path,
        anchor=anchor,
        failure_context=context.get("failure_context") if isinstance(context.get("failure_context"), dict) else {"files": []},
        patch_plan=request.patch_plan if isinstance(request.patch_plan, dict) else {},
    )
    insert_result, insert_timed_out = run_with_provider_heartbeat(
        task_options,
        "insert-after content generation",
        lambda: generate_text_fn(
            provider=provider,
            model=model,
            prompt=prompt,
            api_key_env=context.get("api_key_env"),
            base_url=str(context.get("base_url", "") or ""),
        ),
        timeout_seconds=timeout_seconds,
    )
    if insert_timed_out:
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="provider_timeout",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if not isinstance(insert_result, dict) or not bool(insert_result.get("available", False)):
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=str((insert_result or {}).get("error", "provider_error")) if isinstance(insert_result, dict) else "provider_error",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    insert_text = str(insert_result.get("text", "") or "")
    insert_ok, insert_content, insert_parse_error = _parse_insert_provider_response(insert_text)
    if not insert_ok or insert_content is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=insert_parse_error or INSERT_OUTPUT_INVALID,
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
    original_text = str(context.get("insert_original_text")) if context.get("insert_original_text") is not None else target_file.read_text(encoding="utf-8", errors="replace")
    anchor_index_value = context.get("insert_anchor_index")
    if anchor_index_value is None:
        anchor_ok, anchor_index, anchor_error = resolve_insert_after_index(original_text=original_text, anchor=anchor)
        if not anchor_ok or anchor_index is None:
            return OperationResult(
                attempted=True,
                status="blocked",
                error=anchor_error or OPERATION_CONTRACT_INVALID,
                provider=provider or None,
                model=model or None,
                operation=request.contract.operation,
                source=request.contract.source,
            )
        anchor_index_value = int(anchor_index)

    inserted_text = insert_after_index(
        original_text=original_text,
        index=int(anchor_index_value),
        insert_content=insert_content,
    )
    insert_diff = _build_insert_after_diff(
        target_path=target_path,
        original_text=original_text,
        new_text=inserted_text,
    )
    ok_insert, validate_error = _validate_insert_diff(
        diff_text=insert_diff,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok_insert or not insert_diff:
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
        diff_text=insert_diff,
        error=None,
        provider=provider or None,
        model=model or None,
        operation=request.contract.operation,
        source=request.contract.source,
    )
