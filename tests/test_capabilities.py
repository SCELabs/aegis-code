from __future__ import annotations

from pathlib import Path

from aegis_code.context.capabilities import detect_capabilities


def test_detect_python_with_tests(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "python"
    assert caps["verification_available"] is True
    assert caps["test_command"] == "python -m pytest -q"
    assert caps["confidence"] == "high"


def test_detect_node_with_test_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node"
    assert caps["verification_available"] is True
    assert caps["test_command"] == "npm test"
    assert caps["package_manager"] == "npm"


def test_detect_node_pnpm_package_manager_selects_pnpm_test(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","packageManager":"pnpm@9.0.0","scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["test_command"] == "pnpm test"
    assert caps["package_manager"] == "pnpm"


def test_detect_node_yarn_lockfile_selects_yarn_test(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"jest"}}', encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["test_command"] == "yarn test"
    assert caps["package_manager"] == "yarn"


def test_detect_node_bun_lockfile_selects_bun_test(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")
    (tmp_path / "bun.lockb").write_text("", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["test_command"] == "bun test"
    assert caps["package_manager"] == "bun"


def test_detect_node_package_lock_selects_npm_test(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["test_command"] == "npm test"
    assert caps["package_manager"] == "npm"


def test_package_manager_field_beats_lockfile(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","packageManager":"pnpm@9.0.0","scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    (tmp_path / "yarn.lock").write_text("", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["test_command"] == "pnpm test"
    assert caps["package_manager"] == "pnpm"


def test_detect_node_without_test_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node"
    assert caps["verification_available"] is False
    assert caps["test_command"] is None


def test_detect_node_react_variant(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","dependencies":{"react":"^18.0.0"},"scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node-react"


def test_detect_node_vite_variant_from_dependency(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","devDependencies":{"vite":"^5.0.0"},"scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node-vite"


def test_detect_node_vite_variant_from_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","scripts":{"dev":"vite","test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node-vite"


def test_detect_node_react_vite_variant(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","dependencies":{"react":"^18.0.0"},"devDependencies":{"vite":"^5.0.0"},"scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node-react-vite"


def test_detect_rust(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "rust"
    assert caps["test_command"] == "cargo test"


def test_detect_go(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module x\n", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "go"
    assert caps["test_command"] == "go test ./..."


def test_detect_maven(tmp_path: Path) -> None:
    (tmp_path / "pom.xml").write_text("<project/>", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "java"
    assert caps["test_command"] == "mvn test"


def test_detect_gradle_with_wrapper(tmp_path: Path) -> None:
    (tmp_path / "build.gradle").write_text("plugins {}", encoding="utf-8")
    (tmp_path / "gradlew").write_text("", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "java"
    assert caps["test_command"] == "./gradlew test"


def test_detect_unknown_repo(tmp_path: Path) -> None:
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] is None
    assert caps["verification_available"] is False
    assert caps["test_command"] is None
    assert caps["confidence"] == "low"
    assert caps["package_manager"] is None


def test_detect_python_fastapi_signal_from_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "python-fastapi"
    assert caps["verification_available"] is False
    assert caps["test_command"] is None


def test_detect_python_fastapi_signal_from_app_main_import(tmp_path: Path) -> None:
    (tmp_path / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "main.py").write_text(
        "from fastapi import FastAPI\napp = FastAPI()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "python-fastapi"
    assert caps["verification_available"] is True
    assert caps["test_command"] == "python -m pytest -q"
