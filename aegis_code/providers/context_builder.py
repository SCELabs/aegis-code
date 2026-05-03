from __future__ import annotations

from typing import Any
import re

from aegis_code.patches.constraints import (
    build_tests_only_insertion_hint,
    detect_named_test_file,
)


def line_safe_cap(content: str, limit: int) -> str:
    text = str(content or "")
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    newline_idx = cut.rfind("\n")
    if newline_idx == -1:
        return f"[context truncated: {len(text) - limit} chars omitted]"
    kept = cut[: newline_idx + 1]
    omitted = len(text) - len(kept)
    return kept + f"[context truncated: {omitted} chars omitted]"


def trim_context(context: dict[str, Any], max_chars: int) -> dict[str, Any]:
    if max_chars <= 0:
        return {"files": []}
    files = context.get("files", [])
    if not isinstance(files, list):
        return {"files": []}
    trimmed: list[dict[str, str]] = []
    remaining = max_chars
    for item in files:
        path = str(item.get("path", ""))
        content = str(item.get("content", ""))
        if not path:
            continue
        chunk = line_safe_cap(content, remaining)
        trimmed.append({"path": path, "content": chunk})
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return {"files": trimmed}


def extract_named_test_file(task: str) -> str:
    return detect_named_test_file(task)


def build_named_test_file_context(path: str, content: str) -> dict[str, Any]:
    source = str(content or "")
    lines = source.splitlines()
    if source and not source.endswith(("\n", "\r")) and lines:
        lines = lines[:-1]
    lines = [line for line in lines if line.strip() != "[truncated]"]
    import_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            import_lines.append(line)
            continue
        if stripped == "":
            continue
        break
    symbols: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def test_") or stripped.startswith("class "):
            symbols.append(stripped)
    class_header = ""
    class_methods: list[str] = []
    class_last_method: list[str] = []
    class_idx = -1
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("class TestAegisResult"):
            class_header = stripped
            class_idx = idx
            break
    if class_idx >= 0:
        method_indexes: list[int] = []
        for idx in range(class_idx + 1, len(lines)):
            line = lines[idx]
            stripped = line.strip()
            if stripped.startswith("class ") and not line.startswith((" ", "\t")):
                break
            if stripped.startswith("def test_"):
                class_methods.append(stripped)
                method_indexes.append(idx)
        if method_indexes:
            start = method_indexes[-1]
            end = len(lines)
            for idx in range(start + 1, len(lines)):
                stripped = lines[idx].strip()
                if stripped.startswith("def test_") or (stripped.startswith("class ") and not lines[idx].startswith((" ", "\t"))):
                    end = idx
                    break
            class_last_method = lines[start:end]
            while class_last_method and class_last_method[-1].strip() == "":
                class_last_method.pop()
    tail_lines = lines[-80:] if len(lines) > 80 else list(lines)
    while tail_lines and tail_lines[-1].strip() == "":
        tail_lines.pop()
    return {
        "path": path,
        "imports": import_lines,
        "symbols": symbols,
        "class_anchor": {
            "header": class_header,
            "methods": class_methods,
            "last_method": "\n".join(class_last_method),
        },
        "tail": "\n".join(tail_lines),
    }


def build_insertion_hint() -> str:
    return build_tests_only_insertion_hint("", target_file=None)


def shape_test_generation_context(
    *,
    task: str,
    context: dict[str, Any],
    patch_plan: dict[str, Any],
) -> dict[str, Any]:
    named_file = extract_named_test_file(task)
    target_file = str(patch_plan.get("target_file", "")).strip()
    chosen = named_file or (target_file if target_file.startswith("tests/") else "")
    files = context.get("files", []) if isinstance(context, dict) else []
    if not isinstance(files, list):
        return {"files": []}
    if not chosen:
        filtered = [
            {"path": str(item.get("path", "")), "content": str(item.get("content", ""))}
            for item in files
            if isinstance(item, dict) and str(item.get("path", "")).startswith("tests/")
        ]
        return {"files": filtered[:2]}
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if path != chosen:
            continue
        content = str(item.get("content", ""))
        failing_nodeid = str(patch_plan.get("failing_test_nodeid", "") or "").strip()
        failing_error = str(patch_plan.get("failing_test_error", "") or "").strip()
        if failing_nodeid:
            focused = build_failure_fix_context(
                context={"files": files},
                target_file=path,
                failing_nodeid=failing_nodeid,
                failing_error=failing_error,
            )
            if focused:
                return focused
        shaped = build_named_test_file_context(path, content)
        shaped["insertion_hint"] = build_insertion_hint()
        return {"files": [shaped]}
    return {"files": []}


def _extract_import_lines(lines: list[str]) -> list[str]:
    imports: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            imports.append(line)
            continue
        if stripped == "":
            continue
        break
    return imports


def _extract_function_block(lines: list[str], start: int) -> str:
    if start < 0 or start >= len(lines):
        return ""
    head = lines[start]
    indent = len(head) - len(head.lstrip(" "))
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        line = lines[idx]
        stripped = line.strip()
        if not stripped:
            continue
        line_indent = len(line) - len(line.lstrip(" "))
        if line_indent <= indent and (stripped.startswith("def ") or stripped.startswith("class ")):
            end = idx
            break
    block = lines[start:end]
    while block and block[-1].strip() == "":
        block.pop()
    return "\n".join(block)


def _find_class_block(lines: list[str], class_name: str) -> tuple[int, int]:
    class_line = re.compile(rf"^\s*class\s+{re.escape(class_name)}\b")
    class_start = -1
    class_indent = 0
    for idx, line in enumerate(lines):
        if class_line.match(line):
            class_start = idx
            class_indent = len(line) - len(line.lstrip(" "))
            break
    if class_start < 0:
        return -1, -1
    class_end = len(lines)
    for idx in range(class_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if not stripped:
            continue
        indent = len(lines[idx]) - len(lines[idx].lstrip(" "))
        if indent <= class_indent and stripped.startswith("class "):
            class_end = idx
            break
    return class_start, class_end


def _find_function_start(lines: list[str], func_name: str, begin: int = 0, end: int | None = None) -> int:
    finish = len(lines) if end is None else max(begin, min(end, len(lines)))
    func_line = re.compile(rf"^\s*def\s+{re.escape(func_name)}\s*\(")
    for idx in range(begin, finish):
        if func_line.match(lines[idx]):
            return idx
    return -1


def build_failure_fix_context(
    *,
    context: dict[str, Any],
    target_file: str,
    failing_nodeid: str,
    failing_error: str,
) -> dict[str, Any]:
    files = context.get("files", []) if isinstance(context, dict) else []
    if not isinstance(files, list):
        return {}
    target_content = ""
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "")).strip()
        if path == str(target_file).strip():
            target_content = str(item.get("content", ""))
            break
    if not target_content:
        return {}
    lines = target_content.splitlines()
    if target_content and not target_content.endswith(("\n", "\r")) and lines:
        lines = lines[:-1]
    imports = _extract_import_lines(lines)

    node = str(failing_nodeid or "").replace("\\", "/")
    parts = [p for p in node.split("::") if p]
    func_name = parts[-1] if parts else ""
    class_name = parts[-2] if len(parts) >= 3 else ""
    start = -1
    if class_name:
        class_start, class_end = _find_class_block(lines, class_name)
        if class_start >= 0:
            start = _find_function_start(lines, func_name, begin=class_start + 1, end=class_end)
    if start < 0 and func_name:
        start = _find_function_start(lines, func_name)
    function_source = _extract_function_block(lines, start) if start >= 0 else ""

    error = str(failing_error or "").strip()
    assert_essence = error
    if "AssertionError" in error:
        assert_essence = error.split("AssertionError", 1)[1].strip(" :|-")

    return {
        "files": [
            {
                "path": target_file,
                "imports": imports,
                "failing_nodeid": node,
                "failing_test_function": func_name,
                "failing_test_source": function_source,
                "assertion_essence": assert_essence,
                "insertion_hint": "Modify only the failing test function.",
            }
        ]
    }
