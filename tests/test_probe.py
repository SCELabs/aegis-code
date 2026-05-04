from __future__ import annotations

import json
from pathlib import Path

from aegis_code.probe import get_capabilities, load_capabilities, run_project_probe


def test_probe_creates_capabilities_file(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    path = tmp_path / ".aegis" / "capabilities.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["detected_stack"] in {"python", "python-fastapi"}
    assert loaded["test_command"] == "python -m pytest -q"
    assert loaded["verification_available"] is True
    assert isinstance(payload["last_probe_at"], str)


def test_load_capabilities_returns_none_for_malformed_json(tmp_path: Path) -> None:
    cap_path = tmp_path / ".aegis" / "capabilities.json"
    cap_path.parent.mkdir(parents=True, exist_ok=True)
    cap_path.write_text("{not-json", encoding="utf-8")
    assert load_capabilities(tmp_path) is None


def test_get_capabilities_falls_back_when_file_missing(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    caps = get_capabilities(tmp_path)
    assert caps["test_command"] == "python -m pytest -q"
    assert caps["verification_available"] is True


def test_get_capabilities_falls_back_when_file_incomplete(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    cap_path = tmp_path / ".aegis" / "capabilities.json"
    cap_path.parent.mkdir(parents=True, exist_ok=True)
    cap_path.write_text(json.dumps({"detected_stack": "python"}), encoding="utf-8")
    caps = get_capabilities(tmp_path)
    assert caps["test_command"] == "python -m pytest -q"
    assert caps["verification_available"] is True


def test_test_command_detection_persists(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")
    run_project_probe(cwd=tmp_path, run_tests=False)
    loaded = load_capabilities(tmp_path)
    assert isinstance(loaded, dict)
    assert loaded["test_command"] == "npm test"
    assert loaded["verification_available"] is True


def test_probe_python_detection_with_mocked_which(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setattr("aegis_code.probe.shutil.which", lambda name: "/usr/bin/python" if name in {"python", "git"} else None)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["python_available"] is True
    assert payload["node_available"] is False
    assert payload["git_available"] is True


def test_probe_node_detection_with_mocked_which(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    monkeypatch.setattr("aegis_code.probe.shutil.which", lambda name: "/usr/bin/node" if name == "node" else None)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["node_available"] is True


def test_probe_package_manager_detection(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","packageManager":"pnpm@9.0.0"}', encoding="utf-8")
    monkeypatch.setattr("aegis_code.probe.shutil.which", lambda name: "/usr/bin/pnpm" if name == "pnpm" else None)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["package_manager"] == "pnpm"
    assert payload["package_manager_available"] is True


def test_probe_package_json_script_parsing(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","scripts":{"test":"vitest","build":"vite build","lint":"eslint .","format":"prettier -w ."}}',
        encoding="utf-8",
    )
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["test_command_available"] is True
    assert payload["build_command_available"] is True
    assert payload["lint_command_available"] is True
    assert payload["format_command_available"] is True


def test_probe_python_heuristic_detection(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.black]\nline-length = 100\n[tool.ruff]\nline-length = 100\n",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["test_command_available"] is True
    assert payload["lint_command_available"] is True
    assert payload["format_command_available"] is True


def test_probe_persists_extended_capability_fields(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")
    run_project_probe(cwd=tmp_path, run_tests=False)
    loaded = load_capabilities(tmp_path)
    assert isinstance(loaded, dict)
    for key in (
        "python_available",
        "node_available",
        "git_available",
        "package_manager_available",
        "test_command_available",
        "build_command_available",
        "lint_command_available",
        "format_command_available",
    ):
        assert key in loaded
