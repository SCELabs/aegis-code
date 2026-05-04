from __future__ import annotations

import json
from datetime import datetime, timezone
import shutil
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.tools.shell import run_shell_command


_CAPABILITIES_FILE = ".aegis/capabilities.json"
_SHORT_TEST_PREFIXES = (
    "python -m pytest",
    "pytest",
    "npm test",
    "pnpm test",
    "yarn test",
    "bun test",
    "go test",
    "cargo test",
)
_PYTHON_LINT_HINTS = ("ruff", "flake8", "pylint")
_PYTHON_FORMAT_HINTS = ("black", "isort", "ruff format")


def _capabilities_path(cwd: Path | None = None) -> Path:
    root = (cwd or Path.cwd()).resolve()
    return root / _CAPABILITIES_FILE


def load_capabilities(cwd: Path | None = None) -> dict[str, Any] | None:
    path = _capabilities_path(cwd)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def save_capabilities(data: dict[str, Any], cwd: Path | None = None) -> None:
    path = _capabilities_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def load_observed_capabilities(cwd: Path | None = None) -> dict[str, Any] | None:
    # Backward-compatible alias used across existing modules.
    return load_capabilities(cwd)


def _runtime_available_for_language(language: str | None) -> bool:
    lowered = str(language or "").strip().lower()
    if lowered == "python":
        return bool(shutil.which("python"))
    if lowered in {"javascript", "typescript"}:
        return any(bool(shutil.which(name)) for name in ("node", "npm", "pnpm", "yarn", "bun"))
    if lowered == "go":
        return bool(shutil.which("go"))
    if lowered == "rust":
        return bool(shutil.which("cargo"))
    if lowered == "java":
        return any(bool(shutil.which(name)) for name in ("mvn", "gradle", "java"))
    return False


def _which_any(names: tuple[str, ...]) -> bool:
    return any(bool(shutil.which(name)) for name in names)


def _python_available() -> bool:
    return _which_any(("python", "python3"))


def _node_available() -> bool:
    return bool(shutil.which("node"))


def _git_available() -> bool:
    return bool(shutil.which("git"))


def _is_short_running_test_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().lower().split())
    return any(normalized.startswith(prefix) for prefix in _SHORT_TEST_PREFIXES)


def _detect_install_command(detected: dict[str, Any], root: Path) -> str | None:
    package_manager = str(detected.get("package_manager") or "").strip()
    if package_manager and (root / "package.json").exists():
        return f"{package_manager} install"
    if (root / "requirements.txt").exists():
        return "pip install -r requirements.txt"
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "pip install -e ."
    return None


def _detect_build_command(detected: dict[str, Any], root: Path) -> str | None:
    package_manager = str(detected.get("package_manager") or "").strip()
    if package_manager and (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
            if isinstance(scripts, dict) and isinstance(scripts.get("build"), str) and scripts.get("build", "").strip():
                return f"{package_manager} run build"
        except Exception:
            return None
    if (root / "Makefile").exists():
        return "make build"
    return None


def _detect_lint_command(detected: dict[str, Any], root: Path) -> str | None:
    package_manager = str(detected.get("package_manager") or "").strip()
    if package_manager and (root / "package.json").exists():
        try:
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
            if isinstance(scripts, dict) and isinstance(scripts.get("lint"), str) and scripts.get("lint", "").strip():
                return f"{package_manager} run lint"
        except Exception:
            return None
    if shutil.which("ruff") and (root / "pyproject.toml").exists():
        return "ruff check ."
    return None


def _verification_confidence(verification_available: bool, runtime_available: bool) -> str:
    if verification_available and runtime_available:
        return "high"
    if verification_available:
        return "medium"
    return "low"


def _load_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _python_lightweight_text(root: Path) -> str:
    snippets: list[str] = []
    for rel in ("pyproject.toml", "requirements.txt", "setup.cfg", "tox.ini", ".flake8", "pylintrc"):
        path = root / rel
        if path.exists():
            try:
                snippets.append(path.read_text(encoding="utf-8", errors="replace")[:5000].lower())
            except Exception:
                pass
    return "\n".join(snippets)


def _caps_incomplete(data: dict[str, Any] | None) -> bool:
    if not isinstance(data, dict):
        return True
    required = {
        "detected_stack",
        "language",
        "package_manager",
        "runtime_available",
        "install_command",
        "install_command_worked",
        "test_command",
        "test_command_observed",
        "test_exit_code",
        "build_command",
        "build_command_observed",
        "lint_command",
        "lint_command_observed",
        "verification_available",
        "verification_confidence",
        "signals",
        "last_probe_at",
        "python_available",
        "node_available",
        "git_available",
        "package_manager_available",
        "test_command_available",
        "build_command_available",
        "lint_command_available",
        "format_command_available",
    }
    return not required.issubset(set(data.keys()))


def get_capabilities(cwd: Path | None = None) -> dict[str, Any]:
    loaded = load_capabilities(cwd)
    if not _caps_incomplete(loaded):
        return dict(loaded or {})
    inferred = detect_capabilities(cwd)
    runtime_available = _runtime_available_for_language(inferred.get("language"))
    verification_available = bool(inferred.get("verification_available", False))
    return {
        "detected_stack": inferred.get("detected_stack"),
        "language": inferred.get("language"),
        "package_manager": inferred.get("package_manager"),
        "runtime_available": runtime_available,
        "install_command": None,
        "install_command_worked": None,
        "test_command": inferred.get("test_command"),
        "test_command_observed": False,
        "test_exit_code": None,
        "build_command": None,
        "build_command_observed": False,
        "lint_command": None,
        "lint_command_observed": False,
        "verification_available": verification_available,
        "verification_confidence": _verification_confidence(verification_available, runtime_available),
        "signals": list(inferred.get("signals", [])),
        "last_probe_at": "",
        "python_available": _python_available(),
        "node_available": _node_available(),
        "git_available": _git_available(),
        "package_manager_available": False,
        "test_command_available": bool(inferred.get("test_command")),
        "build_command_available": False,
        "lint_command_available": False,
        "format_command_available": False,
    }


def run_project_probe(
    *,
    cwd: Path | None = None,
    run_tests: bool = False,
    timeout_seconds: int = 8,
) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    project_paths(root)["aegis_dir"].mkdir(parents=True, exist_ok=True)
    detected = detect_capabilities(root)
    package_json = _load_package_json(root)
    scripts = package_json.get("scripts", {}) if isinstance(package_json.get("scripts", {}), dict) else {}
    test_command = str(detected.get("test_command") or "").strip() or None
    runtime_available = _runtime_available_for_language(detected.get("language"))
    install_command = _detect_install_command(detected, root)
    build_command = _detect_build_command(detected, root)
    lint_command = _detect_lint_command(detected, root)
    package_manager = str(detected.get("package_manager") or "").strip()
    package_manager_available = bool(package_manager) and bool(shutil.which(package_manager))
    python_available = _python_available()
    node_available = _node_available()
    git_available = _git_available()

    test_command_available = False
    build_command_available = False
    lint_command_available = False
    format_command_available = False

    if (root / "package.json").exists():
        test_command_available = isinstance(scripts.get("test"), str) and bool(str(scripts.get("test", "")).strip())
        build_command_available = isinstance(scripts.get("build"), str) and bool(str(scripts.get("build", "")).strip())
        lint_command_available = isinstance(scripts.get("lint"), str) and bool(str(scripts.get("lint", "")).strip())
        format_command_available = isinstance(scripts.get("format"), str) and bool(str(scripts.get("format", "")).strip())
    else:
        python_text = _python_lightweight_text(root)
        has_tests_dir = (root / "tests").exists()
        test_command_available = bool(test_command) or has_tests_dir or ("pytest" in python_text)
        lint_command_available = any(hint in python_text for hint in _PYTHON_LINT_HINTS)
        format_command_available = any(hint in python_text for hint in _PYTHON_FORMAT_HINTS)

    test_command_observed = False
    test_exit_code: int | None = None
    if run_tests and test_command and _is_short_running_test_command(test_command):
        result = run_shell_command(
            name="probe_test",
            command=test_command,
            cwd=root,
            timeout_seconds=max(5, min(int(timeout_seconds), 10)),
        )
        if result.status != "timeout":
            test_command_observed = True
            test_exit_code = result.exit_code

    verification_available = bool(test_command)
    payload: dict[str, Any] = {
        "detected_stack": detected.get("detected_stack"),
        "language": detected.get("language"),
        "package_manager": detected.get("package_manager"),
        "runtime_available": runtime_available,
        "install_command": install_command,
        "install_command_worked": None,
        "test_command": test_command,
        "test_command_observed": test_command_observed,
        "test_exit_code": test_exit_code,
        "build_command": build_command,
        "build_command_observed": False,
        "lint_command": lint_command,
        "lint_command_observed": False,
        "verification_available": verification_available,
        "verification_confidence": _verification_confidence(verification_available, runtime_available),
        "signals": list(detected.get("signals", [])),
        "last_probe_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "python_available": python_available,
        "node_available": node_available,
        "git_available": git_available,
        "package_manager_available": package_manager_available,
        "test_command_available": test_command_available,
        "build_command_available": build_command_available,
        "lint_command_available": lint_command_available,
        "format_command_available": format_command_available,
    }
    existing = load_capabilities(root) or {}
    if isinstance(existing, dict):
        existing.update(payload)
        payload = existing
    save_capabilities(payload, root)
    return payload
