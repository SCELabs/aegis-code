from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from aegis_code.config import load_config, project_paths
from aegis_code.context.capabilities import detect_capabilities
from aegis_code.tools.shell import run_shell_command


_MARKERS = [
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "pytest.ini",
    "tox.ini",
    "Makefile",
    "pnpm-lock.yaml",
    "yarn.lock",
    "bun.lock",
    "bun.lockb",
    "package-lock.json",
]

_RUNTIMES = ["python", "pip", "npm", "pnpm", "yarn", "bun", "pytest", "make"]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        return {}
    return {}


def load_observed_capabilities(cwd: Path | None = None) -> dict[str, Any] | None:
    root = (cwd or Path.cwd()).resolve()
    path = project_paths(root)["aegis_dir"] / "capabilities.json"
    if not path.exists():
        return None
    data = _load_json(path)
    if int(data.get("version", 0) or 0) != 1:
        return None
    return data


def _runtime_status() -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for name in _RUNTIMES:
        resolved = shutil.which(name)
        payload[name] = {"available": bool(resolved), "path": str(resolved) if resolved else None}
    return payload


def _load_package_json(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    return _load_json(path)


def _detect_package_manager(root: Path, package_json: dict[str, Any]) -> str | None:
    manager = str(package_json.get("packageManager", "") or "").strip().lower()
    if manager.startswith("pnpm@"):
        return "pnpm"
    if manager.startswith("yarn@"):
        return "yarn"
    if manager.startswith("bun@"):
        return "bun"
    if manager.startswith("npm@"):
        return "npm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lock").exists() or (root / "bun.lockb").exists():
        return "bun"
    if (root / "package-lock.json").exists():
        return "npm"
    if (root / "package.json").exists():
        return "npm"
    return None


def _make_has_test_target(root: Path) -> bool:
    makefile = root / "Makefile"
    if not makefile.exists():
        return False
    try:
        text = makefile.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return re.search(r"(?m)^test\s*:", text) is not None


def _has_python_project_markers(root: Path) -> bool:
    return any((root / name).exists() for name in ("pyproject.toml", "requirements.txt", "setup.py", "pytest.ini", "tox.ini"))


def _has_python_test_signals(root: Path) -> bool:
    if (root / "pytest.ini").exists():
        return True
    tests_dir = root / "tests"
    if not tests_dir.exists():
        return False
    for path in tests_dir.rglob("*.py"):
        if path.is_file():
            return True
    return False


def supports_python_tests(root: Path) -> bool:
    return _has_python_test_signals(root) or _has_python_project_markers(root)


def supports_node_tests(root: Path, package_json: dict[str, Any]) -> bool:
    if not (root / "package.json").exists():
        return False
    scripts = package_json.get("scripts", {}) if isinstance(package_json, dict) else {}
    return isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and bool(scripts.get("test", "").strip())


def supports_make_test(root: Path) -> bool:
    return _make_has_test_target(root)


def _candidate(
    *,
    command: str,
    ecosystem: str,
    executable_available: bool,
    project_supported: bool,
    reason: str,
    block_reason: str | None = None,
) -> dict[str, Any]:
    available = bool(executable_available and project_supported)
    resolved_block_reason = block_reason
    if not resolved_block_reason and not available:
        if not project_supported:
            resolved_block_reason = "project_support_missing"
        elif not executable_available:
            resolved_block_reason = "executable_missing"
    return {
        "command": command,
        "ecosystem": ecosystem,
        "available": available,
        "executable_available": bool(executable_available),
        "project_supported": bool(project_supported),
        "reason": reason,
        "block_reason": resolved_block_reason,
    }


def _build_install_candidates(
    *,
    root: Path,
    package_manager: str | None,
    runtimes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    requirements = root / "requirements.txt"
    pyproject = root / "pyproject.toml"
    setup_py = root / "setup.py"
    package_json = root / "package.json"

    if requirements.exists():
        executable_available = bool(runtimes.get("pip", {}).get("available", False))
        candidates.append(
            _candidate(
                command="pip install -r requirements.txt",
                ecosystem="python",
                executable_available=executable_available,
                project_supported=True,
                reason="requirements.txt found",
            )
        )
    if pyproject.exists() or setup_py.exists():
        executable_available = bool(runtimes.get("pip", {}).get("available", False))
        candidates.append(
            _candidate(
                command="pip install -e .",
                ecosystem="python",
                executable_available=executable_available,
                project_supported=True,
                reason="pyproject.toml/setup.py found",
            )
        )
    if package_json.exists() and package_manager:
        executable_available = bool(runtimes.get(package_manager, {}).get("available", False))
        candidates.append(
            _candidate(
                command=f"{package_manager} install",
                ecosystem="node",
                executable_available=executable_available,
                project_supported=True,
                reason="package.json found",
            )
        )
    return candidates


def _build_test_candidates(
    *,
    root: Path,
    package_json: dict[str, Any],
    package_manager: str | None,
    runtimes: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    has_package_json = (root / "package.json").exists()
    has_python_markers = _has_python_project_markers(root)
    python_supported = supports_python_tests(root)
    node_supported = supports_node_tests(root, package_json)
    make_supported = supports_make_test(root)

    if package_manager:
        executable_available = bool(runtimes.get(package_manager, {}).get("available", False))
        candidates.append(
            _candidate(
                command=f"{package_manager} test",
                ecosystem="node",
                executable_available=executable_available,
                project_supported=node_supported,
                reason="package.json scripts.test detected",
                block_reason=None if node_supported else "no_node_test_script",
            )
        )
    if not has_package_json or has_python_markers:
        candidates.append(
            _candidate(
                command="python -m pytest -q",
                ecosystem="python",
                executable_available=bool(runtimes.get("python", {}).get("available", False)),
                project_supported=python_supported,
                reason="python test markers detected",
                block_reason=None if python_supported else "no_python_test_markers",
            )
        )
        candidates.append(
            _candidate(
                command="pytest -q",
                ecosystem="python",
                executable_available=bool(runtimes.get("pytest", {}).get("available", False)),
                project_supported=python_supported,
                reason="python test markers detected",
                block_reason=None if python_supported else "no_python_test_markers",
            )
        )
    candidates.append(
        _candidate(
            command="make test",
            ecosystem="make",
            executable_available=bool(runtimes.get("make", {}).get("available", False)),
            project_supported=make_supported,
            reason="Makefile test target detected",
            block_reason=None if make_supported else "no_make_test_target",
        )
    )
    return candidates


def _available_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in candidates if bool(item.get("available", False))]


def _support_strengths(root: Path, package_json: dict[str, Any]) -> dict[str, int]:
    strengths: dict[str, int] = {"python": 0, "node": 0, "make": 0}
    if supports_python_tests(root):
        strengths["python"] = 2 if _has_python_test_signals(root) else 1
    if supports_node_tests(root, package_json):
        strengths["node"] = 2
    if supports_make_test(root):
        strengths["make"] = 1
    return strengths


def _rank_key(candidate: dict[str, Any], strengths: dict[str, int]) -> tuple[int, str, str]:
    ecosystem = str(candidate.get("ecosystem", "") or "")
    command = str(candidate.get("command", "") or "")
    command_priority = 10
    if command == "python -m pytest -q":
        command_priority = 0
    elif command == "pytest -q":
        command_priority = 1
    elif command.endswith(" test") and ecosystem == "node":
        command_priority = 2
    elif command == "make test":
        command_priority = 3
    return (-int(strengths.get(ecosystem, 0)), command_priority, ecosystem, command)


def _pick_selected_test(
    *,
    root: Path,
    candidates: list[dict[str, Any]],
    package_json: dict[str, Any],
) -> str | None:
    available = _available_candidates(candidates)
    if not available:
        return None

    config_path = project_paths(root)["config_path"]
    if config_path.exists():
        cfg_command = str(load_config(root).commands.test or "").strip()
        if cfg_command:
            for item in available:
                if str(item.get("command", "")).strip() == cfg_command:
                    return cfg_command

    previous = load_observed_capabilities(root)
    if isinstance(previous, dict):
        prev_command = str(previous.get("selected_test_command", "") or "").strip()
        if prev_command:
            for item in available:
                if str(item.get("command", "")).strip() == prev_command:
                    return prev_command

    strengths = _support_strengths(root, package_json)
    sorted_candidates = sorted(available, key=lambda item: _rank_key(item, strengths))
    for item in sorted_candidates:
        command = str(item.get("command", "") or "").strip()
        if command:
            return command
    return None


def run_project_probe(
    *,
    cwd: Path | None = None,
    run_tests: bool = False,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    root = (cwd or Path.cwd()).resolve()
    paths = project_paths(root)
    paths["aegis_dir"].mkdir(parents=True, exist_ok=True)

    package_json = _load_package_json(root)
    package_manager = _detect_package_manager(root, package_json)
    markers = [name for name in _MARKERS if (root / name).exists()]
    runtimes = _runtime_status()
    install_candidates = _build_install_candidates(root=root, package_manager=package_manager, runtimes=runtimes)
    test_candidates = _build_test_candidates(
        root=root,
        package_json=package_json,
        package_manager=package_manager,
        runtimes=runtimes,
    )
    selected_test_command = _pick_selected_test(root=root, candidates=test_candidates, package_json=package_json)
    observed_runs: list[dict[str, Any]] = []

    if run_tests:
        for candidate in _available_candidates(test_candidates):
            if not bool(candidate.get("available", False)):
                continue
            command = str(candidate.get("command", "") or "").strip()
            if not command:
                continue
            result = run_shell_command(name="probe_test", command=command, cwd=root, timeout_seconds=timeout_seconds)
            observed_runs.append(
                {
                    "command": command,
                    "exit_code": result.exit_code,
                    "status": result.status,
                    "output_preview": result.output_preview,
                }
            )

    verification_available = selected_test_command is not None
    if verification_available:
        confidence = "high"
        reason = "safe test command candidate available"
        environment_issue = False
    elif any(bool(item.get("project_supported", False)) for item in test_candidates):
        confidence = "low"
        reason = "runtime_missing_for_candidates"
        environment_issue = True
    else:
        confidence = "low"
        reason = "no test command candidates detected"
        environment_issue = False

    inferred = detect_capabilities(root)
    payload = {
        "version": 1,
        "detected_stack": inferred.get("detected_stack"),
        "package_manager": package_manager,
        "project_markers": markers,
        "runtimes": runtimes,
        "install_candidates": install_candidates,
        "test_candidates": test_candidates,
        "selected_test_command": selected_test_command,
        "verification": {
            "available": verification_available,
            "confidence": confidence,
            "reason": reason,
            "environment_issue": environment_issue,
        },
        "observed_runs": observed_runs,
    }
    out_path = paths["aegis_dir"] / "capabilities.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
