from __future__ import annotations

import re
from typing import Any


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
    match = re.search(r"(tests/[A-Za-z0-9_./-]+\.py)", str(task or ""))
    if not match:
        return ""
    return match.group(1).strip()


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
    return "Append a new test method at the end of class TestAegisResult."


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
        shaped = build_named_test_file_context(path, content)
        shaped["insertion_hint"] = build_insertion_hint()
        return {"files": [shaped]}
    return {"files": []}
