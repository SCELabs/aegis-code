from __future__ import annotations

import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aegis_code.operations.errors import CREATE_FILE_OUTPUT_INVALID, OPERATION_VALIDATION_FAILED
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _parse_create_file_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, CREATE_FILE_OUTPUT_INVALID
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, flags=re.DOTALL | re.IGNORECASE)
    payload_text = fenced.group(1).strip() if fenced else raw
    if any(marker in payload_text for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    try:
        payload = json.loads(payload_text)
    except Exception:
        return False, None, CREATE_FILE_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    normalized = content if content.endswith("\n") else f"{content}\n"
    if any(marker in normalized for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, CREATE_FILE_OUTPUT_INVALID
    return True, normalized, None


def _build_create_file_diff(*, target_path: str, new_content: str) -> str:
    old_lines: list[str] = []
    new_lines = str(new_content or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile="/dev/null", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\nnew file mode 100644\n".format(target_path) + "\n".join(body) + "\n"


def _target_exists(*, cwd: Path, target_path: str) -> bool:
    return ((cwd.resolve() / str(target_path or "")).resolve()).exists()


def _validate_create_file_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
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
    old_path = file_entry.get("old_path")
    new_path = str(file_entry.get("new_path", "") or "")
    if old_path is not None:
        return False, OPERATION_VALIDATION_FAILED
    if new_path != target_path:
        return False, OPERATION_VALIDATION_FAILED
    if int(summary.get("additions", 0) or 0) <= 0:
        return False, OPERATION_VALIDATION_FAILED
    return True, None


def run_create_file_operation(request: OperationRequest) -> OperationResult:
    from aegis_code.operations.runner import OperationResult

    context = request.context if isinstance(request.context, dict) else {}
    provider = str(context.get("provider", "") or "")
    model = str(request.model or context.get("model", "") or "")
    run_with_provider_heartbeat = context.get("run_with_provider_heartbeat")
    generate_text_fn = context.get("generate_text")
    build_prompt_fn = context.get("build_create_file_prompt")
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
    prompt = build_prompt_fn(
        task=request.task,
        target_path=target_path,
        failure_context=context.get("failure_context") if isinstance(context.get("failure_context"), dict) else {"files": []},
        patch_plan=request.patch_plan if isinstance(request.patch_plan, dict) else {},
    )
    create_result, create_timed_out = run_with_provider_heartbeat(
        task_options,
        "create-file content generation",
        lambda: generate_text_fn(
            provider=provider,
            model=model,
            prompt=prompt,
            api_key_env=context.get("api_key_env"),
            base_url=str(context.get("base_url", "") or ""),
        ),
        timeout_seconds=timeout_seconds,
    )
    if create_timed_out:
        return OperationResult(
            attempted=True,
            status="unavailable",
            error="provider_timeout",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    if not isinstance(create_result, dict) or not bool(create_result.get("available", False)):
        return OperationResult(
            attempted=True,
            status="unavailable",
            error=str((create_result or {}).get("error", "provider_error")) if isinstance(create_result, dict) else "provider_error",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    create_text = str(create_result.get("text", "") or "")
    create_ok, create_content, create_parse_error = _parse_create_file_provider_response(create_text)
    if not create_ok or create_content is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=create_parse_error or CREATE_FILE_OUTPUT_INVALID,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    create_diff = _build_create_file_diff(target_path=target_path, new_content=create_content)
    ok_create, create_error = _validate_create_file_diff(
        diff_text=create_diff,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok_create or not create_diff:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=create_error,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    return OperationResult(
        attempted=True,
        status="generated",
        diff_text=create_diff,
        error=None,
        provider=provider or None,
        model=model or None,
        operation=request.contract.operation,
        source=request.contract.source,
    )
