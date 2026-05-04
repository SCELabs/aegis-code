from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.secrets import set_key


def test_doctor_prints_capability_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    monkeypatch.setattr(
        "aegis_code.cli.check_sll_available",
        lambda: {"available": False, "import_path": "structural_language_lab", "error": "missing"},
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code Doctor" in out
    assert "Stack: python" in out
    assert "Verification:" in out
    assert "command: python -m pytest -q" in out


def test_doctor_does_not_run_runtime(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no tests")))
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code Doctor" in out


def test_doctor_shows_provider_name_and_base_url(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text(
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai-compatible\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n"
        "  base_url: \"http://localhost:11434/v1\"\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Provider:" in out
    assert "name: openai-compatible" in out
    assert "base_url: http://localhost:11434/v1" in out
    assert "Aegis API key: missing (source: missing)" in out
    assert "Aegis Base URL:" in out
    assert "Provider key: missing (source: missing)" in out


def test_doctor_output_includes_environment_section(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "aegis_code.cli.diagnose_environment",
        lambda _cwd, **_kwargs: {
            "python": {"available": True, "version": "Python 3.12.0", "warning": None, "suggestion": None},
            "node": {"available": False, "version": None, "warning": None, "suggestion": None},
            "npm": {"available": False, "version": None, "warning": None, "suggestion": None},
            "git": {"available": True, "version": "git version 2.46.0", "warning": None, "suggestion": None},
            "build_tools": {"available": None, "warning": None, "suggestion": None},
            "issues": [{"warning": "Node.js/npm required for this project but not available.", "suggestion": "Install Node.js 18+ and rerun aegis-code probe --run."}],
        },
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Environment:" in out
    assert "Python: Python 3.12.0" in out
    assert "Node: missing" in out
    assert "npm: missing" in out
    assert "Git: git version 2.46.0" in out
    assert "Environment issues:" in out


def test_doctor_reports_key_sources(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("AEGIS_API_KEY", "aegis-secret", tmp_path, scope="global")
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path, scope="global")
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis API key: configured (source: global)" in out
    assert "Provider key: configured (source:" in out


def test_doctor_openai_provider_shows_default_base_url_label(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text(
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Provider:" in out
    assert "name: openai" in out
    assert "base_url: default OpenAI API" in out


def test_doctor_reports_missing_openai_package_when_provider_enabled(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.environment.importlib.util.find_spec", lambda _name: None)
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text(
        "providers:\n"
        "  enabled: true\n"
        "  provider: \"openai\"\n"
        "  api_key_env: \"OPENAI_API_KEY\"\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "OpenAI provider is enabled but the openai package is not installed." in out
