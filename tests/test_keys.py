from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.secrets import load_secrets


def test_load_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert load_secrets(tmp_path) == {}


def test_set_key(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["keys", "set", "openai_api_key", "secret-value"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Key set: OPENAI_API_KEY" in out
    assert "secret-value" not in out
    data = load_secrets(tmp_path)
    assert data["OPENAI_API_KEY"] == "secret-value"


def test_clear_key(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "AEGIS_API_KEY", "abc"]) == 0
    exit_code = cli.main(["keys", "clear", "aegis_api_key"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Key cleared: AEGIS_API_KEY" in out
    assert "AEGIS_API_KEY" not in load_secrets(tmp_path)


def test_status(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "abc"]) == 0
    exit_code = cli.main(["keys", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Keys:" in out
    assert "- OPENAI_API_KEY: set" in out
    assert "- AEGIS_API_KEY: not set" in out
    assert "abc" not in out


def test_gitignore_updated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "abc"]) == 0
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".aegis/secrets.local.json" in content
    assert ".env" in content
