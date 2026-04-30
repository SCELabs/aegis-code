from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.secrets import load_secrets, mask_key


def test_mask_key_behavior() -> None:
    assert mask_key("abcd") == "****"
    assert mask_key("abcdefgh") == "********"
    assert mask_key("abcdefghijkl") == "abcd****ijkl"


def test_set_key_project_default_masks_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["keys", "set", "openai_api_key", "secret-value"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Stored OPENAI_API_KEY:" in out
    assert "secret-value" not in out
    assert "Scope: project" in out
    data = load_secrets(tmp_path, scope="project")
    assert data["OPENAI_API_KEY"] == "secret-value"


def test_set_key_global_scope(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    exit_code = cli.main(["keys", "set", "AEGIS_API_KEY", "abc", "--global"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Scope: global" in out
    assert load_secrets(tmp_path, scope="global")["AEGIS_API_KEY"] == "abc"


def test_set_key_with_getpass_when_value_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "hidden-value")
    exit_code = cli.main(["keys", "set", "OPENAI_API_KEY"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "hidden-value" not in out
    assert load_secrets(tmp_path, scope="project")["OPENAI_API_KEY"] == "hidden-value"


def test_set_key_non_interactive_missing_value_fails(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    exit_code = cli.main(["keys", "set", "OPENAI_API_KEY"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Missing value for OPENAI_API_KEY" in out


def test_overwrite_prompt_defaults_no(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "one"]) == 0
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    exit_code = cli.main(["keys", "set", "OPENAI_API_KEY", "two"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Cancelled." in out
    assert load_secrets(tmp_path, scope="project")["OPENAI_API_KEY"] == "one"


def test_overwrite_yes_updates_value(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "one"]) == 0
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "two", "--yes"]) == 0
    assert load_secrets(tmp_path, scope="project")["OPENAI_API_KEY"] == "two"


def test_keys_list_masks_values(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "project-secret"]) == 0
    assert cli.main(["keys", "set", "AEGIS_API_KEY", "global-secret", "--global"]) == 0
    exit_code = cli.main(["keys", "list"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "GLOBAL:" in out and "PROJECT:" in out
    assert "project-secret" not in out
    assert "global-secret" not in out


def test_keys_status_shows_source_not_values(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AEGIS_HOME", str(tmp_path / "home" / ".aegis"))
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "global-secret", "--global"]) == 0
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret")
    exit_code = cli.main(["keys", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "KEY                SOURCE      PRESENT" in out
    assert "OPENAI_API_KEY" in out and "env" in out
    assert "env-secret" not in out
    assert "global-secret" not in out


def test_project_secret_is_gitignored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["keys", "set", "OPENAI_API_KEY", "abc"]) == 0
    content = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".aegis/secrets.json" in content

