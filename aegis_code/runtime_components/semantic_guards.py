from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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

