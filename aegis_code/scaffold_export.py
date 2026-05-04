from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from aegis_code.context.capabilities import detect_capabilities

MAX_FILE_BYTES = 100 * 1024

_INCLUDE_FILES = {
    "README.md",
    "pyproject.toml",
    "package.json",
    "requirements.txt",
    "tsconfig.json",
    "vite.config.js",
    "vite.config.ts",
    ".env.example",
}
_INCLUDE_DIRS = {"src", "app", "tests", "public"}
_EXCLUDE_DIRS = {
    ".git",
    ".aegis",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
_EXCLUDE_FILES = {
    ".env",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "uv.lock",
    "poetry.lock",
}


def _is_windows_abs_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]", str(value or "")))


def _is_binary_file(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except Exception:
        return True
    if b"\x00" in data:
        return True
    return False


def _should_include(rel_path: str) -> bool:
    parts = [part for part in rel_path.split("/") if part]
    if not parts:
        return False
    if any(part in _EXCLUDE_DIRS for part in parts):
        return False
    filename = parts[-1]
    if filename in _EXCLUDE_FILES:
        return False
    if rel_path in _INCLUDE_FILES:
        return True
    if parts[0] in _INCLUDE_DIRS:
        return True
    return False


def _safe_repo_relative(source: Path, file_path: Path) -> str | None:
    try:
        rel = file_path.resolve().relative_to(source.resolve())
    except Exception:
        return None
    rel_str = rel.as_posix()
    if rel_str.startswith("../") or rel_str == "..":
        return None
    if Path(rel_str).is_absolute() or _is_windows_abs_path(rel_str):
        return None
    if any(part == ".." for part in rel_str.split("/")):
        return None
    return rel_str


def _detect_build_command(source: Path, capabilities: dict[str, Any]) -> str | None:
    package_json = source / "package.json"
    if not package_json.exists():
        return None
    try:
        pkg = json.loads(package_json.read_text(encoding="utf-8"))
    except Exception:
        return None
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    if not (isinstance(scripts, dict) and isinstance(scripts.get("build"), str) and scripts.get("build", "").strip()):
        return None
    pm = str(capabilities.get("package_manager") or "npm")
    if pm == "yarn":
        return "yarn build"
    return f"{pm} run build"


def _profile_yaml(*, name: str, files: list[dict[str, str]], test_command: str | None, build_command: str | None) -> str:
    lines: list[str] = [
        f"name: {name}",
        'description: "Exported scaffold profile from existing repository."',
        "files:",
    ]
    for item in files:
        path = item["path"]
        content = item["content"]
        lines.append(f"  - path: {path}")
        lines.append("    content: |")
        content_lines = content.splitlines()
        if not content_lines:
            lines.append("      ")
        else:
            for line in content_lines:
                lines.append(f"      {line}")
    lines.extend(
        [
            "commands:",
            "  install: null",
            f"  test: {json.dumps(test_command) if test_command is not None else 'null'}",
            f"  build: {json.dumps(build_command) if build_command is not None else 'null'}",
            "validation:",
            "  expected_files:",
        ]
    )
    for item in files:
        lines.append(f"    - {item['path']}")
    lines.extend(
        [
            "  expected_signals:",
            "    - exported",
        ]
    )
    return "\n".join(lines) + "\n"


def export_scaffold_profile(source: Path, output: Path, name: str | None = None) -> dict:
    try:
        source_path = source.resolve()
        output_path = output.resolve()
        if not source_path.exists() or not source_path.is_dir():
            return {
                "ok": False,
                "profile_path": None,
                "file_count": 0,
                "skipped": [],
                "message": "Source path not found or not a directory.",
            }
        if output_path == source_path:
            return {
                "ok": False,
                "profile_path": None,
                "file_count": 0,
                "skipped": [],
                "message": "Output path must be a file path, not the source directory.",
            }
        if output_path.name in {"", ".", ".."}:
            return {
                "ok": False,
                "profile_path": None,
                "file_count": 0,
                "skipped": [],
                "message": "Invalid output filename.",
            }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_rel = _safe_repo_relative(source_path, output_path)

        files: list[dict[str, str]] = []
        skipped: list[str] = []
        for path in sorted(source_path.rglob("*")):
            if not path.is_file():
                continue
            rel = _safe_repo_relative(source_path, path)
            if not rel:
                skipped.append(str(path))
                continue
            if output_rel and rel == output_rel:
                skipped.append(f"output_profile:{rel}")
                continue
            if not _should_include(rel):
                skipped.append(rel)
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                skipped.append(rel)
                continue
            if _is_binary_file(path):
                skipped.append(rel)
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                skipped.append(rel)
                continue
            files.append({"path": rel, "content": content})

        capabilities = detect_capabilities(source_path)
        test_command = capabilities.get("test_command")
        test_value = str(test_command).strip() if isinstance(test_command, str) and str(test_command).strip() else None
        build_value = _detect_build_command(source_path, capabilities)
        profile_name = str(name or source_path.name or "exported-scaffold")
        output_text = _profile_yaml(
            name=profile_name,
            files=files,
            test_command=test_value,
            build_command=build_value,
        )
        output_path.write_text(output_text, encoding="utf-8")
        return {
            "ok": True,
            "profile_path": str(output_path),
            "file_count": len(files),
            "skipped": skipped,
            "message": "Scaffold profile exported.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "profile_path": None,
            "file_count": 0,
            "skipped": [],
            "message": str(exc),
        }
