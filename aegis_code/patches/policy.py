from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from aegis_code.context.capabilities import detect_capabilities

PLACEHOLDER_MARKERS = (
    "[...truncated...]",
    "...truncated...",
    "<truncated>",
    "[truncated]",
    "TODO: existing content",
    "# existing content",
    "# rest of file",
    "... rest of file ...",
    "... existing code ...",
)


def _task_intent_tokens(task_text: str) -> set[str]:
    stop = {
        "add",
        "tests",
        "test",
        "for",
        "the",
        "only",
        "existing",
        "behavior",
        "do",
        "not",
        "modify",
        "source",
        "files",
        "and",
        "with",
        "aegis",
        "code",
    }
    tokens = re.findall(r"[a-zA-Z_]{4,}", str(task_text or "").lower())
    return {tok for tok in tokens if tok not in stop}


def _task_requests_readme_title_change(task_text: str) -> bool:
    lowered = str(task_text or "").lower()
    title_tokens = (
        "rename readme title",
        "change readme title",
        "update readme title",
        "change title",
        "rename title",
        "retitle",
        "project name",
    )
    return any(token in lowered for token in title_tokens)


def _readme_title_changed(diff_text: str) -> bool:
    removed: list[str] = []
    added: list[str] = []
    for line in str(diff_text or "").splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        removed_match = re.match(r"^-\s*#\s+(.+?)\s*$", line)
        if removed_match:
            removed.append(removed_match.group(1).strip())
            continue
        added_match = re.match(r"^\+\s*#\s+(.+?)\s*$", line)
        if added_match:
            added.append(added_match.group(1).strip())
    if not removed or not added:
        return False
    return removed[0] != added[0]


def _todo_contract_incoherent(diff_text: str, task_text: str) -> bool:
    lowered_task = str(task_text or "").lower()
    if "todo" not in lowered_task or not any(token in lowered_task for token in ("endpoint", "route", "/todos", "api")):
        return False
    lines = str(diff_text or "").splitlines()
    current_target = ""
    src_added: list[str] = []
    test_docs_added: list[str] = []
    for line in lines:
        if line.startswith("+++ "):
            current_target = line[4:].strip()
            if current_target.startswith("a/") or current_target.startswith("b/"):
                current_target = current_target[2:]
            continue
        if not line.startswith("+") or line.startswith("+++ "):
            continue
        content = line[1:]
        normalized = current_target.replace("\\", "/").lower()
        if normalized.startswith("tests/") or normalized == "readme.md" or normalized.startswith("docs/"):
            test_docs_added.append(content)
        elif normalized.endswith(".py"):
            src_added.append(content)
    tests_docs_blob = "\n".join(test_docs_added).lower()
    src_blob = "\n".join(src_added).lower()
    expects_id = any(token in tests_docs_blob for token in ('["id"]', "['id']", '"id"', " id:"))
    expects_description = "description" in tests_docs_blob
    impl_has_id_generation = any(token in src_blob for token in ("uuid4(", "uuid.uuid4", '"id"', "'id'"))
    impl_has_description = "description" in src_blob
    if expects_id and not impl_has_id_generation:
        return True
    if expects_description and not impl_has_description:
        return True
    return False


def _task_requests_destructive_change(task_text: str) -> bool:
    lowered = str(task_text or "").lower()
    patterns = (
        r"\bremove\s+(?:existing\s+)?(?:function|class|method|export|api|route|file|files|section|summary|title|module)\b",
        r"\bdelete\s+(?:existing\s+)?(?:function|class|method|export|api|route|file|files|section|summary|title|module)\b",
        r"\bremove\s+[a-z_][a-z0-9_]*\b",
        r"\bdelete\s+[a-z_][a-z0-9_]*\b",
        r"\bdrop\s+(?:function|class|method|export|api|route|file|files|section)\b",
        r"\brewrite\s+(?:file|module|api|section|readme|summary|title)\b",
        r"\breplace\s+(?:file|module|api|section|readme|summary|title)\b",
        r"\brename\b",
        r"\brefactor\b",
        r"\bdeprecate\b",
    )
    if re.search(r"\badd\s+delete[a-z_0-9]*\s*\(", lowered):
        return False
    return any(re.search(pat, lowered) for pat in patterns)


def _is_additive_task(task_text: str) -> bool:
    lowered = str(task_text or "").lower()
    if not any(token in lowered for token in ("add ", "append ", "new ")):
        return False
    if _task_requests_destructive_change(task_text):
        return False
    return True


def _collect_changed_lines_by_file(diff_text: str) -> dict[str, dict[str, list[str]]]:
    current_target = ""
    changed: dict[str, dict[str, list[str]]] = {}
    for raw_line in str(diff_text or "").splitlines():
        if raw_line.startswith("+++ "):
            current_target = raw_line[4:].strip()
            if current_target.startswith("a/") or current_target.startswith("b/"):
                current_target = current_target[2:]
            current_target = current_target.replace("\\", "/")
            changed.setdefault(current_target, {"added": [], "removed": []})
            continue
        if not current_target:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++ "):
            changed[current_target]["added"].append(raw_line[1:].rstrip("\r"))
        elif raw_line.startswith("-") and not raw_line.startswith("--- "):
            changed[current_target]["removed"].append(raw_line[1:].rstrip("\r"))
    return changed


def _python_public_symbol_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        fn = re.match(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if fn:
            names.add(fn.group(1))
            continue
        cls = re.match(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\(|:)", line)
        if cls:
            names.add(cls.group(1))
    return names


def _js_exported_symbol_names(lines: list[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        for pat in (
            r"^\s*export\s+function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(",
            r"^\s*export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\{|extends|\()",
            r"^\s*export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
            r"^\s*export\s+let\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
            r"^\s*export\s+var\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
            r"^\s*exports\.([A-Za-z_][A-Za-z0-9_]*)\s*=",
        ):
            m = re.match(pat, line)
            if m:
                names.add(m.group(1))
    return names


def _is_source_file(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    if not normalized:
        return False
    if normalized.startswith("tests/") or normalized == "readme.md" or normalized.startswith("docs/"):
        return False
    return normalized.endswith((".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"))


def _is_js_project(cwd: Path | None) -> bool:
    if cwd is None:
        return False
    try:
        caps = detect_capabilities(cwd)
    except Exception:
        return False
    stack = str(caps.get("detected_stack", "") or "")
    language = str(caps.get("language", "") or "")
    return stack.startswith("node") or language in {"javascript", "typescript"}


def _has_node_test_usage(cwd: Path | None) -> bool:
    if cwd is None:
        return False
    ignore_dirs = {".git", ".aegis", "node_modules", "dist", "build", ".venv", "venv", "__pycache__"}
    try:
        for path in cwd.rglob("*"):
            if not path.is_file():
                continue
            if any(part in ignore_dirs for part in path.parts):
                continue
            rel = str(path.relative_to(cwd)).replace("\\", "/").lower()
            if not (rel.startswith("tests/") or rel.endswith(".test.js") or rel.endswith(".spec.js") or rel.endswith(".test.ts") or rel.endswith(".spec.ts")):
                continue
            if path.suffix.lower() not in {".js", ".mjs", ".cjs", ".ts", ".mts", ".cts"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "node:test" in text:
                return True
    except Exception:
        return False
    return False


def _added_lines_use_python_style(lines: list[str]) -> bool:
    blob = "\n".join(lines)
    patterns = (
        r"```+\s*python\b",
        r"\bpython\s+-m\b",
        r"^\s*def\s+[A-Za-z_][A-Za-z0-9_]*\s*\(",
        r"^\s*class\s+[A-Za-z_][A-Za-z0-9_]*\s*:",
        r"^\s*print\s*\(",
        r"\blen\s*\(",
        r"^\s*del\s+[A-Za-z_][A-Za-z0-9_]*\s*\[[^\]]+\]",
        r"if __name__ == ['\"]__main__['\"]",
    )
    return any(re.search(pat, blob, flags=re.IGNORECASE | re.MULTILINE) for pat in patterns)


def hard_invalid_content_evaluate(
    *,
    diff_text: str,
    validation: dict[str, Any],
    test_task: bool,
    task_text: str,
    cwd: Path | None = None,
) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "policy_checked": False,
        "policy_input_files": [],
        "policy_input_length": 0,
        "policy_input_preview": "",
        "detected_additive_task": False,
        "detected_destructive_intent": False,
        "detected_project_stack": None,
        "detected_js_project": False,
        "detected_node_test": False,
        "detected_removed_public_symbols": [],
        "detected_docs_language_mismatch": False,
        "detected_readme_title_change": False,
        "final_policy_reason": None,
    }
    text = str(diff_text or "")
    if not text:
        return diagnostics
    diagnostics["policy_checked"] = True
    diagnostics["policy_input_length"] = len(text)
    diagnostics["policy_input_preview"] = "\n".join(text.splitlines()[:20])
    files = validation.get("files", []) if isinstance(validation, dict) else []
    if isinstance(files, list):
        diagnostics["policy_input_files"] = [
            str(item.get("new_path") or item.get("old_path") or "")
            for item in files
            if isinstance(item, dict)
        ]
    if cwd is not None:
        try:
            caps = detect_capabilities(cwd)
            diagnostics["detected_project_stack"] = caps.get("detected_stack")
            diagnostics["detected_js_project"] = _is_js_project(cwd)
            diagnostics["detected_node_test"] = _has_node_test_usage(cwd)
        except Exception:
            pass
    changed_by_file = _collect_changed_lines_by_file(text)
    lowered = text.lower()
    for marker in PLACEHOLDER_MARKERS:
        if marker.lower() in lowered:
            diagnostics["final_policy_reason"] = "placeholder_content"
            return diagnostics

    if not test_task:
        readme_title_changed = _readme_title_changed(text) and not _task_requests_readme_title_change(task_text)
        diagnostics["detected_readme_title_change"] = bool(readme_title_changed)
        if _todo_contract_incoherent(text, task_text):
            diagnostics["final_policy_reason"] = "contract_incoherent_todo_api"
            return diagnostics
        is_additive = _is_additive_task(task_text)
        destructive_requested = _task_requests_destructive_change(task_text)
        diagnostics["detected_additive_task"] = bool(is_additive)
        diagnostics["detected_destructive_intent"] = bool(destructive_requested)
        removed_public_symbols: set[str] = set()
        test_framework_mismatch = False
        docs_language_mismatch = False
        if is_additive and not destructive_requested:
            for target, payload in changed_by_file.items():
                if not _is_source_file(target):
                    continue
                removed = payload.get("removed", [])
                added = payload.get("added", [])
                normalized = str(target).replace("\\", "/").lower()
                removed_symbols: set[str] = set()
                added_symbols: set[str] = set()
                if normalized.endswith(".py"):
                    removed_symbols = _python_public_symbol_names(removed)
                    added_symbols = _python_public_symbol_names(added)
                elif normalized.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")):
                    removed_symbols = _js_exported_symbol_names(removed)
                    added_symbols = _js_exported_symbol_names(added)
                if removed_symbols:
                    removed_public_symbols.update(removed_symbols)
                if removed_symbols & added_symbols:
                    removed_public_symbols.update(removed_symbols & added_symbols)

        if diagnostics.get("detected_js_project", False):
            node_test = bool(diagnostics.get("detected_node_test", False))
            for target, payload in changed_by_file.items():
                normalized = str(target).replace("\\", "/").lower()
                added_lines = payload.get("added", [])
                if normalized.startswith("tests/") and normalized.endswith((".js", ".mjs", ".cjs", ".ts", ".mts", ".cts")) and node_test:
                    blob = "\n".join(added_lines)
                    if re.search(r"\b(describe|expect|beforeeach)\s*\(", blob, flags=re.IGNORECASE):
                        test_framework_mismatch = True
                    if re.search(r"^\s*const\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*require\s*\(", blob, flags=re.IGNORECASE | re.MULTILINE):
                        test_framework_mismatch = True
                if normalized == "readme.md" or normalized.startswith("docs/"):
                    if _added_lines_use_python_style(added_lines):
                        docs_language_mismatch = True
        diagnostics["detected_removed_public_symbols"] = sorted(removed_public_symbols)
        diagnostics["detected_docs_language_mismatch"] = bool(docs_language_mismatch)
        if removed_public_symbols:
            diagnostics["final_policy_reason"] = "destructive_public_api_rewrite"
            return diagnostics
        if test_framework_mismatch:
            diagnostics["final_policy_reason"] = "ecosystem_test_framework_mismatch"
            return diagnostics
        if docs_language_mismatch:
            diagnostics["final_policy_reason"] = "docs_language_mismatch"
            return diagnostics
        if readme_title_changed:
            diagnostics["final_policy_reason"] = "readme_title_changed"
            return diagnostics

        for item in files if isinstance(files, list) else []:
            if not isinstance(item, dict):
                continue
            target = str(item.get("new_path") or item.get("old_path") or "").lower()
            if not target:
                continue
            is_docs = (
                target == "readme.md"
                or target.endswith(".md")
                or target.startswith("docs/")
            )
            if not is_docs:
                continue
            file_additions = int(item.get("additions", 0) or 0)
            file_deletions = int(item.get("deletions", 0) or 0)
            if file_deletions > 200:
                diagnostics["final_policy_reason"] = "destructive_docs_rewrite"
                return diagnostics
            if file_deletions > 80 and file_additions < (file_deletions / 2):
                diagnostics["final_policy_reason"] = "destructive_docs_rewrite"
                return diagnostics
            if target == "readme.md":
                removed_lines: list[str] = []
                for changed_target, changed_payload in changed_by_file.items():
                    if str(changed_target).replace("\\", "/").lower() == "readme.md":
                        removed_lines.extend(changed_payload.get("removed", []))
                removed_summary = any(re.match(r"^\s*#{1,6}\s*summary\b", line, flags=re.IGNORECASE) for line in removed_lines)
                if removed_summary and not _task_requests_destructive_change(task_text):
                    diagnostics["final_policy_reason"] = "destructive_docs_rewrite"
                    return diagnostics
        return diagnostics

    additions_total = int((validation.get("summary", {}) or {}).get("additions", 0)) if isinstance(validation, dict) else 0
    deletions_total = int((validation.get("summary", {}) or {}).get("deletions", 0)) if isinstance(validation, dict) else 0
    if deletions_total > additions_total * 2 and deletions_total > 20:
        diagnostics["final_policy_reason"] = "destructive_test_rewrite"
        return diagnostics
    intent_tokens = _task_intent_tokens(task_text)
    for item in files if isinstance(files, list) else []:
        if not isinstance(item, dict):
            continue
        target = str(item.get("new_path") or item.get("old_path") or "")
        if not target.startswith("tests/") or not target.endswith(".py"):
            continue
        file_deletions = int(item.get("deletions", 0) or 0)
        if file_deletions > 40:
            diagnostics["final_policy_reason"] = "destructive_test_rewrite"
            return diagnostics
    removed_symbols: list[str] = []
    for raw_line in text.splitlines():
        if raw_line.startswith("--- ") or raw_line.startswith("diff --git ") or raw_line.startswith("@@ "):
            continue
        if not raw_line.startswith("-"):
            continue
        line = raw_line[1:].strip()
        if line.startswith("import ") or line.startswith("from ") or line.startswith("class ") or line.startswith("def test_"):
            removed_symbols.append(line.lower())
    if removed_symbols:
        if not intent_tokens:
            diagnostics["final_policy_reason"] = "destructive_test_rewrite"
            return diagnostics
        symbol_tokens = set()
        for line in removed_symbols:
            symbol_tokens.update(re.findall(r"[a-zA-Z_]{4,}", line))
        if symbol_tokens and not (symbol_tokens & intent_tokens):
            diagnostics["final_policy_reason"] = "destructive_test_rewrite"
            return diagnostics
    return diagnostics


def hard_invalid_content_reason(
    *,
    diff_text: str,
    validation: dict[str, Any],
    test_task: bool,
    task_text: str,
    cwd: Path | None = None,
) -> str | None:
    return hard_invalid_content_evaluate(
        diff_text=diff_text,
        validation=validation,
        test_task=test_task,
        task_text=task_text,
        cwd=cwd,
    ).get("final_policy_reason")


def hard_invalid_reason(
    *,
    syntactic_valid: bool | None,
    additions: int,
    size_threshold: int,
    plan_consistent: bool,
    diff_text: str = "",
    validation: dict[str, Any] | None = None,
    test_task: bool = False,
    task_text: str = "",
    cwd: Path | None = None,
) -> str | None:
    content_reason = hard_invalid_content_reason(
        diff_text=diff_text,
        validation=validation or {},
        test_task=test_task,
        task_text=task_text,
        cwd=cwd,
    )
    if content_reason:
        return content_reason
    if syntactic_valid is False:
        return "syntactic_invalid"
    if additions > size_threshold:
        return "excessive_diff_size"
    if not plan_consistent:
        return "plan_inconsistent"
    return None
