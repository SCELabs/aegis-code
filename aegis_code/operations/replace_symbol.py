from __future__ import annotations

import ast
import json
import re
from difflib import unified_diff
from pathlib import Path
from typing import TYPE_CHECKING

from aegis_code.operations.errors import (
    OPERATION_CONTRACT_INVALID,
    OPERATION_SYMBOL_AMBIGUOUS,
    OPERATION_SYMBOL_NOT_FOUND,
    OPERATION_TARGET_MISSING,
    OPERATION_VALIDATION_FAILED,
    REPLACE_SYMBOL_OUTPUT_INVALID,
)
from aegis_code.patches.diff_inspector import inspect_diff

if TYPE_CHECKING:
    from aegis_code.operations.runner import OperationRequest, OperationResult


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    running = 0
    for line in str(text or "").splitlines(keepends=True):
        running += len(line)
        offsets.append(running)
    return offsets


def _line_col_to_index(*, offsets: list[int], line: int, col: int, text_length: int) -> int:
    line_num = max(1, int(line))
    col_num = max(0, int(col))
    if line_num - 1 >= len(offsets):
        return int(text_length)
    return min(int(text_length), int(offsets[line_num - 1]) + col_num)


def _python_symbol_spans(*, original_text: str, symbol: str) -> list[tuple[int, int]]:
    try:
        tree = ast.parse(str(original_text or ""))
    except Exception:
        return []
    offsets = _line_offsets(original_text)
    text_len = len(str(original_text or ""))
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if str(getattr(node, "name", "")) != str(symbol):
            continue
        start_line = int(getattr(node, "lineno", 0) or 0)
        start_col = int(getattr(node, "col_offset", 0) or 0)
        for decorator in getattr(node, "decorator_list", []):
            dec_line = int(getattr(decorator, "lineno", 0) or 0)
            if dec_line > 0 and (start_line <= 0 or dec_line < start_line):
                start_line = dec_line
                start_col = int(getattr(decorator, "col_offset", 0) or 0)
        end_line = int(getattr(node, "end_lineno", 0) or 0)
        end_col = int(getattr(node, "end_col_offset", 0) or 0)
        if start_line <= 0 or end_line <= 0:
            continue
        start_index = _line_col_to_index(
            offsets=offsets,
            line=start_line,
            col=start_col,
            text_length=text_len,
        )
        end_index = _line_col_to_index(
            offsets=offsets,
            line=end_line,
            col=end_col,
            text_length=text_len,
        )
        if end_index > start_index:
            spans.append((start_index, end_index))
    return spans


def _find_matching_brace(text: str, open_index: int) -> int | None:
    depth = 0
    i = int(open_index)
    in_single = False
    in_double = False
    in_template = False
    in_line_comment = False
    in_block_comment = False
    escape = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_single:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "'":
                in_single = False
            i += 1
            continue
        if in_double:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
            i += 1
            continue
        if in_template:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "`":
                in_template = False
            i += 1
            continue
        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
            if depth < 0:
                return None
        i += 1
    return None


def _match_js_ts_span(*, original_text: str, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(original_text):
        open_index = str(original_text).find("{", match.start(), match.end())
        if open_index < 0:
            continue
        close_index = _find_matching_brace(original_text, open_index)
        if close_index is None:
            continue
        end_index = close_index + 1
        while end_index < len(original_text) and original_text[end_index] in (" ", "\t"):
            end_index += 1
        if end_index < len(original_text) and original_text[end_index] == ";":
            end_index += 1
        spans.append((match.start(), end_index))
    return spans


def _js_ts_symbol_spans(*, original_text: str, symbol: str) -> list[tuple[int, int]]:
    escaped = re.escape(str(symbol))
    function_pattern = re.compile(
        rf"(?ms)^[ \t]*(?:export[ \t]+)?function[ \t]+{escaped}\b[\s\S]*?\{{"
    )
    arrow_pattern = re.compile(
        rf"(?ms)^[ \t]*(?:export[ \t]+)?const[ \t]+{escaped}\b(?:[ \t]*:[^=\n]+)?[ \t]*=[ \t]*(?:async[ \t]+)?\([^)]*\)[ \t]*=>[ \t]*\{{"
    )
    out: list[tuple[int, int]] = []
    out.extend(_match_js_ts_span(original_text=original_text, pattern=function_pattern))
    out.extend(_match_js_ts_span(original_text=original_text, pattern=arrow_pattern))
    dedup: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for item in sorted(out):
        if item not in seen:
            dedup.append(item)
            seen.add(item)
    return dedup


def resolve_symbol_span(
    *,
    original_text: str,
    symbol: str,
    target_path: str,
) -> tuple[bool, tuple[int, int] | None, str | None]:
    symbol_name = str(symbol or "").strip()
    if not symbol_name:
        return False, None, OPERATION_CONTRACT_INVALID
    suffix = str(Path(str(target_path or "")).suffix or "").lower()
    spans: list[tuple[int, int]]
    if suffix == ".py":
        spans = _python_symbol_spans(original_text=original_text, symbol=symbol_name)
    elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}:
        spans = _js_ts_symbol_spans(original_text=original_text, symbol=symbol_name)
    else:
        spans = []
    if not spans:
        return False, None, OPERATION_SYMBOL_NOT_FOUND
    if len(spans) > 1:
        return False, None, OPERATION_SYMBOL_AMBIGUOUS
    return True, spans[0], None


def replace_symbol_span(
    *,
    original_text: str,
    span: tuple[int, int],
    replacement_content: str,
) -> str:
    start, end = int(span[0]), int(span[1])
    return str(original_text or "")[:start] + str(replacement_content or "") + str(original_text or "")[end:]


def _parse_replace_symbol_provider_response(text: str) -> tuple[bool, str | None, str | None]:
    raw = str(text or "").strip()
    if not raw:
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    if "```" in raw:
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    raw_lower = raw.lower()
    if any(marker in raw_lower for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    try:
        payload = json.loads(raw)
    except Exception:
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    if not isinstance(payload, dict):
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    content = payload.get("content")
    if not isinstance(content, str) or not content.strip():
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    content_lower = content.lower()
    if "```" in content or any(marker in content_lower for marker in ("diff --git", "@@", "--- a/", "+++ b/")):
        return False, None, REPLACE_SYMBOL_OUTPUT_INVALID
    return True, content, None


def _build_replace_symbol_diff(*, target_path: str, original_text: str, new_text: str) -> str:
    old_lines = str(original_text or "").splitlines()
    new_lines = str(new_text or "").splitlines()
    body = list(unified_diff(old_lines, new_lines, fromfile=f"a/{target_path}", tofile=f"b/{target_path}", lineterm=""))
    if not body:
        return ""
    return "diff --git a/{0} b/{0}\n".format(target_path) + "\n".join(body) + "\n"


def _validate_replace_symbol_diff(*, diff_text: str, target_path: str, cwd: Path) -> tuple[bool, str | None]:
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


def run_replace_symbol_operation(request: OperationRequest) -> OperationResult:
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
        deps.build_replace_symbol_prompt
        if deps and deps.build_replace_symbol_prompt
        else context.get("build_replace_symbol_prompt")
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
    symbol = str(request.contract.symbol or "").strip()
    if not target_path or not symbol:
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

    original_text = (
        str(context.get("replace_symbol_original_text"))
        if context.get("replace_symbol_original_text") is not None
        else target_file.read_text(encoding="utf-8", errors="replace")
    )
    span_value = context.get("replace_symbol_span")
    resolved_span: tuple[int, int] | None = None
    if (
        isinstance(span_value, (tuple, list))
        and len(span_value) == 2
        and isinstance(span_value[0], int)
        and isinstance(span_value[1], int)
    ):
        resolved_span = (int(span_value[0]), int(span_value[1]))
    if resolved_span is None:
        span_ok, span, span_error = resolve_symbol_span(
            original_text=original_text,
            symbol=symbol,
            target_path=target_path,
        )
        if not span_ok or span is None:
            return OperationResult(
                attempted=True,
                status="blocked",
                error=span_error or OPERATION_SYMBOL_NOT_FOUND,
                provider=provider or None,
                model=model or None,
                operation=request.contract.operation,
                source=request.contract.source,
            )
        resolved_span = span

    prompt = build_prompt_fn(
        task=request.task,
        target_path=target_path,
        symbol=symbol,
        failure_context=context.get("failure_context") if isinstance(context.get("failure_context"), dict) else {"files": []},
        patch_plan=request.patch_plan if isinstance(request.patch_plan, dict) else {},
    )
    replace_result, replace_timed_out = run_with_provider_heartbeat(
        task_options,
        "replace-symbol content generation",
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
    replace_ok, replacement_content, replace_parse_error = _parse_replace_symbol_provider_response(replace_text)
    if not replace_ok or replacement_content is None:
        return OperationResult(
            attempted=True,
            status="blocked",
            error=replace_parse_error or REPLACE_SYMBOL_OUTPUT_INVALID,
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )

    replaced_text = replace_symbol_span(
        original_text=original_text,
        span=resolved_span,
        replacement_content=replacement_content,
    )
    if replaced_text == original_text:
        return OperationResult(
            attempted=True,
            status="blocked",
            error="no_symbol_change",
            provider=provider or None,
            model=model or None,
            operation=request.contract.operation,
            source=request.contract.source,
        )
    replace_diff = _build_replace_symbol_diff(
        target_path=target_path,
        original_text=original_text,
        new_text=replaced_text,
    )
    ok_replace, validate_error = _validate_replace_symbol_diff(
        diff_text=replace_diff,
        target_path=target_path,
        cwd=request.cwd,
    )
    if not ok_replace or not replace_diff:
        return OperationResult(
            attempted=True,
            status="invalid",
            error=validate_error or OPERATION_VALIDATION_FAILED,
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
