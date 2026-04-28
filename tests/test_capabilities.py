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


def test_detect_node_without_test_script(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    caps = detect_capabilities(tmp_path)
    assert caps["detected_stack"] == "node"
    assert caps["verification_available"] is False
    assert caps["test_command"] is None


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
