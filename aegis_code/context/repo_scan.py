from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from aegis_code.models import RepoScanSummary

IGNORED_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".aegis",
}

MAX_SOURCE_FILES = 24
MAX_TEST_FILES = 24
MAX_SYMBOLS_PER_FILE = 24
MAX_TESTS_PER_FILE = 24
MAX_HINT_FILES = 12
MAX_REPO_MAP_CHARS = 8000


def _is_ignored_dir_name(name: str) -> bool:
    return name in IGNORED_DIRS or name.endswith(".egg-info")


def _is_ignored_path(path: Path) -> bool:
    return any(_is_ignored_dir_name(part) for part in path.parts)


def _is_python_file(path: Path) -> bool:
    return path.suffix.lower() == ".py"


def _is_test_file(rel_path: str) -> bool:
    lowered = rel_path.lower()
    name = Path(rel_path).name.lower()
    return lowered.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")


def _extract_symbols(parsed: ast.AST) -> tuple[list[str], list[str], list[str]]:
    functions: list[str] = []
    classes: list[str] = []
    tests: list[str] = []
    for node in getattr(parsed, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = str(getattr(node, "name", "")).strip()
            if name:
                functions.append(name)
                if name.startswith("test_"):
                    tests.append(name)
        elif isinstance(node, ast.ClassDef):
            class_name = str(getattr(node, "name", "")).strip()
            if class_name:
                classes.append(class_name)
            for child in getattr(node, "body", []):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method = str(getattr(child, "name", "")).strip()
                    if method.startswith("test_"):
                        tests.append(f"{class_name}.{method}" if class_name else method)
    return (
        sorted(set(functions))[:MAX_SYMBOLS_PER_FILE],
        sorted(set(classes))[:MAX_SYMBOLS_PER_FILE],
        sorted(set(tests))[:MAX_TESTS_PER_FILE],
    )


def _has_main_guard(parsed: ast.AST) -> bool:
    for node in ast.walk(parsed):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
            continue
        if not isinstance(test.ops[0], ast.Eq):
            continue
        left = test.left
        right = test.comparators[0]
        left_is_name = isinstance(left, ast.Name) and left.id == "__name__"
        right_is_main = isinstance(right, ast.Constant) and right.value == "__main__"
        if left_is_name and right_is_main:
            return True
    return False


def _parse_python_file(path: Path, rel_path: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": rel_path,
        "functions": [],
        "classes": [],
        "tests": [],
        "hints": {
            "main_guard": False,
            "main_function": False,
            "argparse": False,
            "sys_argv": False,
        },
    }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        payload["parse_error"] = "read_error"
        return payload
    payload["hints"]["argparse"] = "argparse" in text
    payload["hints"]["sys_argv"] = "sys.argv" in text
    try:
        parsed = ast.parse(text)
    except Exception:
        payload["parse_error"] = "parse_error"
        return payload
    functions, classes, tests = _extract_symbols(parsed)
    payload["functions"] = functions
    payload["classes"] = classes
    payload["tests"] = tests
    payload["hints"]["main_guard"] = _has_main_guard(parsed)
    payload["hints"]["main_function"] = "main" in functions
    return payload


def _render_repo_map(repo_map: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Repository map (python, lightweight):")
    lines.append("Source files:")
    for item in repo_map.get("source_files", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('path', '')}")
        functions = item.get("functions", [])
        classes = item.get("classes", [])
        if functions:
            lines.append(f"  functions: {', '.join(str(x) for x in functions)}")
        if classes:
            lines.append(f"  classes: {', '.join(str(x) for x in classes)}")
    lines.append("Test files:")
    for item in repo_map.get("test_files", []):
        if not isinstance(item, dict):
            continue
        lines.append(f"- {item.get('path', '')}")
        tests = item.get("tests", [])
        if tests:
            lines.append(f"  tests: {', '.join(str(x) for x in tests)}")
    cli_hints = repo_map.get("cli_hints", {}) if isinstance(repo_map.get("cli_hints"), dict) else {}
    lines.append("CLI hints:")
    for key in ("main_guard_files", "main_function_files", "argparse_files", "sys_argv_files"):
        values = cli_hints.get(key, []) if isinstance(cli_hints.get(key), list) else []
        lines.append(f"- {key}: {', '.join(str(x) for x in values) if values else '(none)'}")
    rendered = "\n".join(lines).strip()
    if len(rendered) > MAX_REPO_MAP_CHARS:
        return rendered[: MAX_REPO_MAP_CHARS - 13] + "\n[truncated]"
    return rendered


def build_python_repo_map(cwd: Path | None = None) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    files: list[tuple[str, Path]] = []
    for path in root.rglob("*.py"):
        if not path.is_file():
            continue
        if _is_ignored_path(path):
            continue
        rel = path.relative_to(root).as_posix()
        files.append((rel, path))
    files.sort(key=lambda item: item[0].lower())

    test_candidates = [item for item in files if _is_test_file(item[0])]
    source_candidates = [item for item in files if not _is_test_file(item[0])]

    source_entries = [_parse_python_file(path, rel) for rel, path in source_candidates[:MAX_SOURCE_FILES]]
    test_entries = [_parse_python_file(path, rel) for rel, path in test_candidates[:MAX_TEST_FILES]]
    source_entries.sort(key=lambda item: str(item.get("path", "")).lower())
    test_entries.sort(key=lambda item: str(item.get("path", "")).lower())

    def _hint_files(name: str) -> list[str]:
        values = [
            str(item.get("path", ""))
            for item in source_entries + test_entries
            if isinstance(item, dict) and isinstance(item.get("hints"), dict) and bool(item["hints"].get(name, False))
        ]
        return sorted(values, key=str.lower)[:MAX_HINT_FILES]

    repo_map: dict[str, Any] = {
        "language": "python",
        "source_files": source_entries,
        "test_files": test_entries,
        "cli_hints": {
            "main_guard_files": _hint_files("main_guard"),
            "main_function_files": _hint_files("main_function"),
            "argparse_files": _hint_files("argparse"),
            "sys_argv_files": _hint_files("sys_argv"),
        },
        "limits": {
            "max_source_files": MAX_SOURCE_FILES,
            "max_test_files": MAX_TEST_FILES,
            "max_symbols_per_file": MAX_SYMBOLS_PER_FILE,
            "max_tests_per_file": MAX_TESTS_PER_FILE,
            "max_chars": MAX_REPO_MAP_CHARS,
        },
    }
    rendered = _render_repo_map(repo_map)
    repo_map["rendered"] = rendered
    repo_map["char_count"] = len(rendered)
    repo_map["truncated"] = bool(len(rendered) >= MAX_REPO_MAP_CHARS and rendered.endswith("[truncated]"))
    return repo_map


def scan_repo(cwd: Path | None = None) -> RepoScanSummary:
    root = cwd or Path.cwd()
    file_count = 0
    top_level_dirs: list[str] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if _is_ignored_dir_name(child.name):
            continue
        if child.is_dir():
            top_level_dirs.append(child.name)

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _is_ignored_path(path):
            continue
        file_count += 1

    return RepoScanSummary(file_count=file_count, top_level_directories=top_level_dirs)
