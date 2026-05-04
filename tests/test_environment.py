from __future__ import annotations

from pathlib import Path
import subprocess

from aegis_code.environment import diagnose_environment


def _cp(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=0, stdout=stdout, stderr=stderr)


def test_python_314_warning(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda _name: "x")

    def _run(cmd, **_kwargs):
        if cmd[0] in {"python", "python3"}:
            return _cp(stdout="Python 3.14.0")
        return _cp(stdout=f"{cmd[0]} 1.0.0")

    monkeypatch.setattr("aegis_code.environment.subprocess.run", _run)
    payload = diagnose_environment(tmp_path)
    issues = payload["issues"]
    assert any("Python 3.14 may lack prebuilt wheels" in str(item.get("warning", "")) for item in issues)


def test_missing_node_npm_with_package_json(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda name: None if name in {"node", "npm"} else "x")
    monkeypatch.setattr("aegis_code.environment.subprocess.run", lambda cmd, **_kwargs: _cp(stdout=f"{cmd[0]} 1.0.0"))
    payload = diagnose_environment(tmp_path)
    issues = payload["issues"]
    assert any("Node.js/npm required for this project but not available." in str(item.get("warning", "")) for item in issues)


def test_native_dependency_warning_from_requirements(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pydantic-core==2.0.0\n", encoding="utf-8")
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda _name: "x")
    monkeypatch.setattr("aegis_code.environment.subprocess.run", lambda cmd, **_kwargs: _cp(stdout=f"{cmd[0]} 1.0.0"))
    payload = diagnose_environment(tmp_path)
    issues = payload["issues"]
    assert any("Native Python dependencies may require build tools." in str(item.get("warning", "")) for item in issues)


def test_native_dependency_warning_from_latest_report(monkeypatch, tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.md").write_text("Failed building wheel\nMicrosoft Visual C++\n", encoding="utf-8")
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda _name: "x")
    monkeypatch.setattr("aegis_code.environment.subprocess.run", lambda cmd, **_kwargs: _cp(stdout=f"{cmd[0]} 1.0.0"))
    payload = diagnose_environment(tmp_path)
    issues = payload["issues"]
    assert any("Native Python dependencies may require build tools." in str(item.get("warning", "")) for item in issues)


def test_no_crash_when_commands_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda _name: None)
    monkeypatch.setattr("aegis_code.environment.subprocess.run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("x")))
    payload = diagnose_environment(tmp_path)
    assert payload["python"]["available"] is False
    assert payload["node"]["available"] is False
    assert payload["npm"]["available"] is False
    assert payload["git"]["available"] is False


def test_openai_provider_enabled_missing_package_issue(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.environment.shutil.which", lambda _name: "x")
    monkeypatch.setattr("aegis_code.environment.subprocess.run", lambda cmd, **_kwargs: _cp(stdout=f"{cmd[0]} 1.0.0"))
    monkeypatch.setattr("aegis_code.environment.importlib.util.find_spec", lambda _name: None)
    payload = diagnose_environment(tmp_path, provider_enabled=True, provider_name="openai")
    issues = payload["issues"]
    assert any("OpenAI provider is enabled but the openai package is not installed." in str(item.get("warning", "")) for item in issues)
