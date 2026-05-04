from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _has_any(root: Path, names: list[str]) -> bool:
    return any((root / name).exists() for name in names)


def _load_package_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _detect_python_fastapi(root: Path, pyproject: Path, requirements: Path) -> bool:
    markers: list[Path] = []
    if pyproject.exists():
        markers.append(pyproject)
    if requirements.exists():
        markers.append(requirements)
    app_main = root / "app" / "main.py"
    if app_main.exists():
        markers.append(app_main)
    for path in markers:
        lowered = _read_text(path).lower()
        if "fastapi" in lowered:
            return True
    # Lightweight deterministic scan for import usage.
    candidates = [
        root / "main.py",
        root / "app.py",
        root / "app" / "__init__.py",
    ]
    for path in candidates:
        if not path.exists():
            continue
        lowered = _read_text(path).lower()
        if "from fastapi import" in lowered or "fastapi(" in lowered:
            return True
    return False


def _detect_node_package_manager(root: Path, pkg: dict[str, Any]) -> str:
    package_manager = str(pkg.get("packageManager", "") or "").strip().lower()
    if package_manager.startswith("pnpm@"):
        return "pnpm"
    if package_manager.startswith("yarn@"):
        return "yarn"
    if package_manager.startswith("bun@"):
        return "bun"
    if package_manager.startswith("npm@"):
        return "npm"
    if (root / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (root / "yarn.lock").exists():
        return "yarn"
    if (root / "bun.lockb").exists() or (root / "bun.lock").exists():
        return "bun"
    if (root / "package-lock.json").exists():
        return "npm"
    return "npm"


def _detect_node_stack(pkg: dict[str, Any]) -> str:
    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = pkg.get(key)
        if isinstance(value, dict):
            deps.update(value)
    dep_names = {str(name).strip().lower() for name in deps.keys()}
    scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
    dev_script = str(scripts.get("dev", "") or "").lower() if isinstance(scripts, dict) else ""
    has_react = "react" in dep_names
    has_vite = "vite" in dep_names or "vite" in dev_script
    if has_react and has_vite:
        return "node-react-vite"
    if has_react:
        return "node-react"
    if has_vite:
        return "node-vite"
    return "node"


def detect_capabilities(cwd: Path | None = None) -> dict[str, Any]:
    root = cwd or Path.cwd()
    signals: list[str] = []

    pyproject = root / "pyproject.toml"
    setup_py = root / "setup.py"
    requirements = root / "requirements.txt"
    pytest_ini = root / "pytest.ini"
    tests_dir = root / "tests"
    package_json = root / "package.json"
    cargo_toml = root / "Cargo.toml"
    go_mod = root / "go.mod"
    pom_xml = root / "pom.xml"
    gradle = root / "build.gradle"
    gradle_kts = root / "build.gradle.kts"
    gradlew = root / "gradlew"

    if pyproject.exists():
        signals.append("pyproject.toml")
    if setup_py.exists():
        signals.append("setup.py")
    if requirements.exists():
        signals.append("requirements.txt")
    if pytest_ini.exists():
        signals.append("pytest.ini")
    if tests_dir.exists():
        signals.append("tests/")

    python_project_markers = _has_any(root, ["pyproject.toml", "setup.py", "requirements.txt", "pytest.ini"])
    python_tests_marker = tests_dir.exists()
    if python_project_markers or (python_tests_marker and not package_json.exists()):
        fastapi_detected = _detect_python_fastapi(root, pyproject, requirements)
        detected_stack = "python-fastapi" if fastapi_detected else "python"
        verification_available = tests_dir.exists() or pytest_ini.exists()
        command = "python -m pytest -q" if verification_available else None
        confidence = "high" if verification_available else "medium"
        if verification_available:
            reason = "tests directory and/or pytest config detected"
        elif fastapi_detected:
            reason = "fastapi markers detected but no pytest entrypoint found"
        else:
            reason = "python project markers detected but no test entrypoint found"
        detected = {
            "detected_stack": detected_stack,
            "language": "python",
            "test_command": command,
            "verification_available": verification_available,
            "confidence": confidence,
            "reason": reason,
            "package_manager": None,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    if package_json.exists():
        signals.append("package.json")
        pkg = _load_package_json(package_json)
        package_manager = _detect_node_package_manager(root, pkg)
        stack = _detect_node_stack(pkg)
        if (root / "pnpm-lock.yaml").exists():
            signals.append("pnpm-lock.yaml")
        if (root / "yarn.lock").exists():
            signals.append("yarn.lock")
        if (root / "bun.lockb").exists():
            signals.append("bun.lockb")
        if (root / "bun.lock").exists():
            signals.append("bun.lock")
        if (root / "package-lock.json").exists():
            signals.append("package-lock.json")
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        has_test = isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and scripts.get("test", "").strip()
        if has_test:
            language = "typescript" if _has_any(root, ["tsconfig.json"]) else "javascript"
            detected = {
                "detected_stack": stack,
                "language": language,
                "test_command": f"{package_manager} test",
                "verification_available": True,
                "confidence": "high",
                "reason": f"package.json test script detected ({package_manager})",
                "package_manager": package_manager,
                "signals": signals,
            }
            return _apply_observed_override(root, detected)
        detected = {
            "detected_stack": stack,
            "language": "javascript",
            "test_command": None,
            "verification_available": False,
            "confidence": "medium",
            "reason": f"node project detected but no test script found ({package_manager})",
            "package_manager": package_manager,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    if cargo_toml.exists():
        signals.append("Cargo.toml")
        detected = {
            "detected_stack": "rust",
            "language": "rust",
            "test_command": "cargo test",
            "verification_available": True,
            "confidence": "high",
            "reason": "Cargo.toml detected",
            "package_manager": None,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    if go_mod.exists():
        signals.append("go.mod")
        detected = {
            "detected_stack": "go",
            "language": "go",
            "test_command": "go test ./...",
            "verification_available": True,
            "confidence": "high",
            "reason": "go.mod detected",
            "package_manager": None,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    if pom_xml.exists():
        signals.append("pom.xml")
        detected = {
            "detected_stack": "java",
            "language": "java",
            "test_command": "mvn test",
            "verification_available": True,
            "confidence": "high",
            "reason": "pom.xml detected",
            "package_manager": None,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    if gradle.exists() or gradle_kts.exists():
        if gradle.exists():
            signals.append("build.gradle")
        if gradle_kts.exists():
            signals.append("build.gradle.kts")
        if gradlew.exists():
            signals.append("gradlew")
        detected = {
            "detected_stack": "java",
            "language": "java",
            "test_command": "./gradlew test" if gradlew.exists() else "gradle test",
            "verification_available": True,
            "confidence": "high",
            "reason": "gradle build file detected",
            "package_manager": None,
            "signals": signals,
        }
        return _apply_observed_override(root, detected)

    detected = {
        "detected_stack": None,
        "language": None,
        "test_command": None,
        "verification_available": False,
        "confidence": "low",
        "reason": "no known test/toolchain markers detected",
        "package_manager": None,
        "signals": signals,
    }
    return _apply_observed_override(root, detected)


def _apply_observed_override(root: Path, detected: dict[str, Any]) -> dict[str, Any]:
    observed_path = root / ".aegis" / "capabilities.json"
    if not observed_path.exists():
        return detected
    try:
        observed = json.loads(observed_path.read_text(encoding="utf-8"))
    except Exception:
        return detected
    if not isinstance(observed, dict):
        return detected
    selected = str(observed.get("test_command", "") or observed.get("selected_test_command", "") or "").strip()
    verification_available = bool(
        observed.get("verification_available", False)
        or (isinstance(observed.get("verification"), dict) and observed.get("verification", {}).get("available", False))
    )
    if not verification_available or not selected:
        return detected
    patched = dict(detected)
    patched["test_command"] = selected
    patched["verification_available"] = True
    patched["confidence"] = str(
        observed.get("verification_confidence")
        or (observed.get("verification", {}) if isinstance(observed.get("verification"), dict) else {}).get("confidence")
        or patched.get("confidence", "medium")
    )
    patched["reason"] = "observed_capabilities"
    if patched.get("detected_stack") in {None, "", "unknown"} and observed.get("detected_stack"):
        patched["detected_stack"] = observed.get("detected_stack")
    if (patched.get("package_manager") in {None, "", "n/a"}) and observed.get("package_manager"):
        patched["package_manager"] = observed.get("package_manager")
    patched["observed_capabilities"] = True
    return patched
