from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run_version_command(command: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    return output or None


def _tool_status(name: str, commands: list[list[str]]) -> dict[str, Any]:
    if shutil.which(name) is None and not any(shutil.which(cmd[0]) for cmd in commands):
        return {"available": False, "version": None, "warning": None, "suggestion": None}
    for cmd in commands:
        version = _run_version_command(cmd)
        if version:
            return {"available": True, "version": version, "warning": None, "suggestion": None}
    return {"available": False, "version": None, "warning": None, "suggestion": None}


def _parse_python_minor(version_text: str | None) -> tuple[int, int] | None:
    if not version_text:
        return None
    match = re.search(r"Python\s+(\d+)\.(\d+)", version_text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _has_native_dependency_indicator(cwd: Path) -> bool:
    indicators = ("pydantic-core", "pydantic", "maturin", "cryptography")
    files = [cwd / "requirements.txt", cwd / "pyproject.toml"]
    for path in files:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except Exception:
            continue
        if any(item in text for item in indicators):
            return True
    return False


def _latest_run_mentions_build_tool_issue(cwd: Path) -> bool:
    needles = (
        "Failed building wheel",
        "link.exe",
        "Microsoft Visual C++",
        "Visual Studio Build Tools",
    )
    for candidate in (cwd / ".aegis" / "runs" / "latest.md", cwd / ".aegis" / "runs" / "latest.json"):
        if not candidate.exists():
            continue
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if any(needle in text for needle in needles):
            return True
    return False


def diagnose_environment(cwd: Path) -> dict:
    python = _tool_status("python", [["python", "--version"], ["python3", "--version"]])
    node = _tool_status("node", [["node", "--version"]])
    npm = _tool_status("npm", [["npm", "--version"]])
    git = _tool_status("git", [["git", "--version"]])
    build_tools: dict[str, Any] = {"available": None, "warning": None, "suggestion": None}
    issues: list[dict[str, str]] = []

    parsed = _parse_python_minor(python.get("version"))
    if parsed and parsed[0] == 3 and parsed[1] >= 14:
        warning = "Python 3.14 may lack prebuilt wheels for some native dependencies."
        suggestion = "Use Python 3.11 or 3.12 for best compatibility."
        python["warning"] = warning
        python["suggestion"] = suggestion
        issues.append({"warning": warning, "suggestion": suggestion})

    package_json = cwd / "package.json"
    if package_json.exists() and (not node.get("available", False) or not npm.get("available", False)):
        warning = "Node.js/npm required for this project but not available."
        suggestion = "Install Node.js 18+ and rerun aegis-code probe --run."
        issues.append({"warning": warning, "suggestion": suggestion})

    if _has_native_dependency_indicator(cwd) or _latest_run_mentions_build_tool_issue(cwd):
        warning = "Native Python dependencies may require build tools."
        suggestion = "Prefer Python 3.11/3.12 with prebuilt wheels, or install Visual Studio C++ Build Tools."
        build_tools["warning"] = warning
        build_tools["suggestion"] = suggestion
        issues.append({"warning": warning, "suggestion": suggestion})

    return {
        "python": python,
        "node": node,
        "npm": npm,
        "git": git,
        "build_tools": build_tools,
        "issues": issues,
    }
