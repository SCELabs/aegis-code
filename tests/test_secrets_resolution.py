from __future__ import annotations

from pathlib import Path

from aegis_code.secrets import resolve_key, resolve_key_source, set_key


def test_env_overrides_project_and_global(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    set_key("OPENAI_API_KEY", "from_global", cwd=tmp_path, scope="global")
    set_key("OPENAI_API_KEY", "from_project", cwd=tmp_path, scope="project")
    monkeypatch.setenv("OPENAI_API_KEY", "from_env")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_env"
    assert resolve_key_source("OPENAI_API_KEY", tmp_path)["source"] == "env"


def test_project_overrides_global(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    set_key("OPENAI_API_KEY", "from_global", cwd=tmp_path, scope="global")
    set_key("OPENAI_API_KEY", "from_project", cwd=tmp_path, scope="project")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_project"
    assert resolve_key_source("OPENAI_API_KEY", tmp_path)["source"] == "project"


def test_global_fallback_works(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    set_key("OPENAI_API_KEY", "from_global", cwd=tmp_path, scope="global")
    assert resolve_key("OPENAI_API_KEY", tmp_path) == "from_global"
    assert resolve_key_source("OPENAI_API_KEY", tmp_path)["source"] == "global"


def test_missing_key_fails_honestly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_key("OPENAI_API_KEY", tmp_path) is None
    source = resolve_key_source("OPENAI_API_KEY", tmp_path)
    assert source["source"] == "missing"
    assert source["present"] is False


def test_project_specific_key_resolves_without_value_exposure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_key("STRIPE_API_KEY", "sk_test_1234567890", cwd=tmp_path, scope="project")
    assert resolve_key("STRIPE_API_KEY", tmp_path) == "sk_test_1234567890"
    src = resolve_key_source("STRIPE_API_KEY", tmp_path)
    assert src["source"] == "project"
    assert src["present"] is True

