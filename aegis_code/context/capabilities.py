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

    if _has_any(root, ["pyproject.toml", "setup.py", "requirements.txt", "pytest.ini", "tests"]):
        verification_available = tests_dir.exists() or pytest_ini.exists()
        command = "python -m pytest -q" if verification_available else None
        confidence = "high" if verification_available else "medium"
        reason = (
            "tests directory and/or pytest config detected"
            if verification_available
            else "python project markers detected but no test entrypoint found"
        )
        return {
            "detected_stack": "python",
            "language": "python",
            "test_command": command,
            "verification_available": verification_available,
            "confidence": confidence,
            "reason": reason,
            "signals": signals,
        }

    if package_json.exists():
        signals.append("package.json")
        if (root / "package-lock.json").exists():
            signals.append("package-lock.json")
        pkg = _load_package_json(package_json)
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        has_test = isinstance(scripts, dict) and isinstance(scripts.get("test"), str) and scripts.get("test", "").strip()
        if has_test:
            language = "typescript" if _has_any(root, ["tsconfig.json"]) else "javascript"
            return {
                "detected_stack": "node",
                "language": language,
                "test_command": "npm test",
                "verification_available": True,
                "confidence": "high",
                "reason": "package.json test script detected",
                "signals": signals,
            }
        return {
            "detected_stack": "node",
            "language": "javascript",
            "test_command": None,
            "verification_available": False,
            "confidence": "medium",
            "reason": "node project detected but no test script found",
            "signals": signals,
        }

    if cargo_toml.exists():
        signals.append("Cargo.toml")
        return {
            "detected_stack": "rust",
            "language": "rust",
            "test_command": "cargo test",
            "verification_available": True,
            "confidence": "high",
            "reason": "Cargo.toml detected",
            "signals": signals,
        }

    if go_mod.exists():
        signals.append("go.mod")
        return {
            "detected_stack": "go",
            "language": "go",
            "test_command": "go test ./...",
            "verification_available": True,
            "confidence": "high",
            "reason": "go.mod detected",
            "signals": signals,
        }

    if pom_xml.exists():
        signals.append("pom.xml")
        return {
            "detected_stack": "java",
            "language": "java",
            "test_command": "mvn test",
            "verification_available": True,
            "confidence": "high",
            "reason": "pom.xml detected",
            "signals": signals,
        }

    if gradle.exists() or gradle_kts.exists():
        if gradle.exists():
            signals.append("build.gradle")
        if gradle_kts.exists():
            signals.append("build.gradle.kts")
        if gradlew.exists():
            signals.append("gradlew")
        return {
            "detected_stack": "java",
            "language": "java",
            "test_command": "./gradlew test" if gradlew.exists() else "gradle test",
            "verification_available": True,
            "confidence": "high",
            "reason": "gradle build file detected",
            "signals": signals,
        }

    return {
        "detected_stack": None,
        "language": None,
        "test_command": None,
        "verification_available": False,
        "confidence": "low",
        "reason": "no known test/toolchain markers detected",
        "signals": signals,
    }
