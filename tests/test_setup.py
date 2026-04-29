from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.setup import run_setup
from aegis_code.secrets import set_key


def test_setup_initializes_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_provider=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["initialized"] is True
    assert (tmp_path / ".aegis" / "aegis-code.yml").exists()
    assert (tmp_path / ".aegis" / "project_model.md").exists()


def test_setup_skip_aegis(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_provider=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["aegis"]["attempted"] is False
    assert result["aegis"]["reason"] == "skipped"


def test_setup_uses_existing_aegis_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("AEGIS_API_KEY", "secret-key", tmp_path)
    result = run_setup(
        cwd=tmp_path,
        skip_provider=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["aegis"]["success"] is True
    assert result["aegis"]["reason"] == "already_configured"


def test_setup_applies_recommended_provider_with_yes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENAI_API_KEY", "openai-key", tmp_path)
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["provider"]["recommended_preset"] == "openai"
    assert result["provider"]["applied_preset"] == "openai"


def test_setup_skips_provider_when_no_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["provider"]["detected"] is True
    assert result["provider"]["recommended_preset"] is None
    assert result["provider"]["applied_preset"] is None


def test_setup_skip_first_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def _boom(**_kwargs):
        raise AssertionError("run_task should not be called when first run is skipped")

    monkeypatch.setattr("aegis_code.setup.run_task", _boom)
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_provider=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["first_run"]["attempted"] is False
    assert result["first_run"]["status"] == "skipped"


def test_cli_setup_outputs_summary(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_setup(**_kwargs):
        return {
            "initialized": True,
            "aegis": {"attempted": False, "success": False, "reason": "skipped"},
            "provider": {"detected": True, "recommended_preset": "openai", "applied_preset": "openai"},
            "first_run": {"attempted": False, "status": "skipped"},
        }

    monkeypatch.setattr("aegis_code.cli.run_setup", _fake_run_setup)
    exit_code = cli.main(["setup", "--yes"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code setup" in out
    assert "Setup complete." in out
    assert "- Initialized: true" in out
    assert "- Aegis: skipped" in out
    assert "- Provider preset: openai" in out
    assert "- First run: skipped" in out
