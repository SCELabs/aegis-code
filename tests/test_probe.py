from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.probe import run_project_probe
from aegis_code.models import CommandResult


def test_probe_detects_python_pytest_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["detected_stack"] in {"python", "python-fastapi"}
    assert payload["selected_test_command"] == "python -m pytest -q"
    assert payload["verification"]["available"] is True


def test_probe_detects_node_project_with_package_manager_pnpm(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"name":"x","packageManager":"pnpm@9.0.0","scripts":{"test":"vitest"}}',
        encoding="utf-8",
    )
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["package_manager"] == "pnpm"
    assert any(item["command"] == "pnpm test" for item in payload["test_candidates"])


def test_probe_does_not_select_global_pytest_without_python_project_support(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"npm test"}}', encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_dummy.js").write_text("test('x', () => {})\n", encoding="utf-8")

    def _fake_which(name: str):
        if name in {"npm", "python", "pytest"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    commands = [item["command"] for item in payload["test_candidates"]]
    assert "npm test" in commands
    assert "python -m pytest -q" not in commands
    assert payload["selected_test_command"] == "npm test"


def test_probe_records_missing_npm_runtime_without_crashing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")

    def _fake_which(name: str):
        if name == "npm":
            return None
        return f"/usr/bin/{name}"

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    npm_state = payload["runtimes"]["npm"]
    assert npm_state["available"] is False
    assert payload["verification"]["available"] is False


def test_probe_node_missing_npm_marks_environment_issue(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")

    def _fake_which(name: str):
        if name == "npm":
            return None
        if name in {"python", "pytest"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["selected_test_command"] is None
    assert payload["verification"]["available"] is False
    assert payload["verification"]["environment_issue"] is True
    assert "runtime_missing" in str(payload["verification"]["reason"])


def test_probe_mixed_project_can_select_python_when_python_markers_present(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_core.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def _fake_which(name: str):
        if name in {"python", "pytest"}:
            return f"/usr/bin/{name}"
        if name == "npm":
            return None
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["selected_test_command"] == "python -m pytest -q"


def test_probe_does_not_select_global_npm_without_package_json_test_script(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")

    def _fake_which(name: str):
        if name in {"npm", "python", "pytest"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["selected_test_command"] is None
    npm_candidate = next(item for item in payload["test_candidates"] if item["command"] == "npm test")
    assert npm_candidate["project_supported"] is False
    assert npm_candidate["available"] is False
    assert npm_candidate["block_reason"] == "no_node_test_script"


def test_probe_selects_pytest_when_python_tests_exist(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")

    def _fake_which(name: str):
        if name in {"python", "pytest"}:
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["selected_test_command"] == "python -m pytest -q"


def test_probe_selects_npm_when_package_json_test_script_and_npm_available(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")

    def _fake_which(name: str):
        if name == "npm":
            return "/usr/bin/npm"
        if name in {"python", "pytest"}:
            return "/usr/bin/" + name
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    assert payload["selected_test_command"] == "npm test"


def test_probe_blocks_candidate_when_executable_missing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x","scripts":{"test":"vitest"}}', encoding="utf-8")

    def _fake_which(name: str):
        if name == "npm":
            return None
        return "/usr/bin/" + name

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    candidate = next(item for item in payload["test_candidates"] if item["command"] == "npm test")
    assert candidate["executable_available"] is False
    assert candidate["available"] is False
    assert candidate["block_reason"] == "executable_missing"


def test_probe_blocks_candidate_when_project_support_missing(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")

    def _fake_which(name: str):
        if name == "npm":
            return "/usr/bin/npm"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    candidate = next(item for item in payload["test_candidates"] if item["command"] == "npm test")
    assert candidate["project_supported"] is False
    assert candidate["available"] is False
    assert candidate["block_reason"] == "no_node_test_script"


def test_probe_make_test_requires_makefile_target(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "Makefile").write_text("all:\n\t@echo hi\n", encoding="utf-8")

    def _fake_which(name: str):
        if name == "make":
            return "/usr/bin/make"
        return None

    monkeypatch.setattr("aegis_code.probe.shutil.which", _fake_which)
    payload = run_project_probe(cwd=tmp_path, run_tests=False)
    make_candidate = next(item for item in payload["test_candidates"] if item["command"] == "make test")
    assert make_candidate["project_supported"] is False
    assert make_candidate["available"] is False
    assert make_candidate["block_reason"] == "no_make_test_target"


def test_probe_writes_capabilities_json(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    run_project_probe(cwd=tmp_path, run_tests=False)
    path = tmp_path / ".aegis" / "capabilities.json"
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["version"] == 1


def test_probe_run_records_observed_run_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_probe.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.probe.run_shell_command",
        lambda **_k: CommandResult(
            name="probe_test",
            command="python -m pytest -q",
            status="ok",
            exit_code=0,
            output_preview="probe pass",
            full_output="probe pass",
        ),
    )
    exit_code = cli.main(["probe", "--run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Probe" in out
    payload = json.loads((tmp_path / ".aegis" / "capabilities.json").read_text(encoding="utf-8"))
    assert payload["observed_runs"]
    assert payload["observed_runs"][0]["output_preview"] == "probe pass"
