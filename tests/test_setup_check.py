from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.config import ensure_project_files
from aegis_code.secrets import set_key
from aegis_code.setup import check_setup


def test_setup_check_empty_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    status = check_setup(tmp_path)
    assert status["initialized"] is False
    assert status["aegis_key"] is False
    assert status["provider_key"] is False
    assert status["provider_preset"] is False
    assert status["context_available"] is False
    assert status["latest_run"] is False


def test_setup_check_initialized_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    ensure_project_files(cwd=tmp_path, force=False)
    status = check_setup(tmp_path)
    assert status["initialized"] is True
    assert status["aegis_key"] is False
    assert status["provider_key"] is False
    assert status["provider_preset"] is True
    assert status["context_available"] is False
    assert status["latest_run"] is False


def test_setup_check_with_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    ensure_project_files(cwd=tmp_path, force=False)
    set_key("AEGIS_API_KEY", "aegis-secret", tmp_path)
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path)
    status = check_setup(tmp_path)
    assert status["initialized"] is True
    assert status["aegis_key"] is True
    assert status["provider_key"] is True


def test_setup_check_full_ready(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    ensure_project_files(cwd=tmp_path, force=False)
    set_key("AEGIS_API_KEY", "aegis-secret", tmp_path)
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("summary\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text("{}", encoding="utf-8")

    exit_code = cli.main(["setup", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Setup Check:" in out
    assert "- Project initialized: true" in out
    assert "- Aegis key: set" in out
    assert "- Provider key: found" in out
    assert "- Provider preset: configured" in out
    assert "- Context: available" in out
    assert "- Latest run: found" in out
    assert "- Verification: available" in out


def test_setup_check_no_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["setup", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "No project initialized. Run `aegis-code setup`." in out
