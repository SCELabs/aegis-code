from __future__ import annotations

from pathlib import Path

from aegis_code.secrets import resolve_key, set_key


def test_resolve_key_env_priority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from_env_file\n", encoding="utf-8")
    set_key("OPENAI_API_KEY", "from_secrets", cwd=tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "from_env")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_env"


def test_resolve_key_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    (tmp_path / ".env").write_text("\n# comment\nOPENAI_API_KEY=from_env_file\n", encoding="utf-8")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_env_file"


def test_resolve_key_secrets_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    set_key("OPENAI_API_KEY", "from_secrets", cwd=tmp_path)
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_secrets"


def test_resolve_key_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_key("OPENAI_API_KEY", tmp_path) is None


def test_resolve_priority_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("OPENAI_API_KEY", "from_secrets", cwd=tmp_path)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=from_env_file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "from_env")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_env"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_env_file"
    (tmp_path / ".env").unlink()
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_secrets"
