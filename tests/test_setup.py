from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.setup import run_setup
from aegis_code.secrets import load_secrets, set_key


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


def test_setup_calls_onboarding_with_global_scope(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake_onboard(email: str, cwd: Path, scope: str = "global") -> dict:
        captured["email"] = email
        captured["cwd"] = cwd
        captured["scope"] = scope
        return {"success": True, "scope": scope}

    monkeypatch.setattr("aegis_code.setup.run_onboard", _fake_onboard)
    result = run_setup(
        cwd=tmp_path,
        email="user@example.com",
        skip_provider=True,
        skip_first_run=True,
        assume_yes=True,
    )
    assert result["aegis"]["success"] is True
    assert captured["scope"] == "global"
    assert load_secrets(tmp_path, scope="global").get("AEGIS_BASE_URL")


def test_setup_provider_prompt_stores_openai_key_globally(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.setup.resolve_key", lambda _name, _cwd: None)
    monkeypatch.setattr("aegis_code.setup._confirm", lambda _prompt, assume_yes: True)
    monkeypatch.setattr("aegis_code.setup.getpass.getpass", lambda _prompt: "openai-secret")
    result = run_setup(
        cwd=tmp_path,
        skip_aegis=True,
        skip_provider=False,
        skip_first_run=True,
        assume_yes=False,
    )
    assert result["provider"]["detected"] is True
    assert load_secrets(tmp_path, scope="global").get("OPENAI_API_KEY") == "openai-secret"


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
            "aegis": {"attempted": False, "success": True, "reason": "already_configured", "base_url": "https://example.aegis"},
            "provider": {"detected": True, "recommended_preset": "openai", "applied_preset": "openai"},
            "first_run": {"attempted": True, "status": "completed_tests_passed"},
        }

    monkeypatch.setattr("aegis_code.cli.run_setup", _fake_run_setup)
    exit_code = cli.main(["setup", "--yes"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code setup" in out
    assert "Setup complete." in out
    assert "Aegis:" in out
    assert "- API key: configured (global)" in out
    assert "- Base URL: https://example.aegis" in out
    assert "Provider:" in out
    assert "- Key: OPENAI_API_KEY (global)" in out
    assert "- Preset: openai" in out
    assert "Try:" in out
    assert 'aegis-code "analyze project structure"' in out
    assert "First run complete:" in out
    assert "- status: completed_tests_passed" in out
    assert "- tests: passed" in out


def test_setup_prints_openai_dependency_hint_when_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_setup(**_kwargs):
        return {
            "initialized": True,
            "aegis": {"attempted": False, "success": True, "reason": "already_configured", "base_url": "https://example.aegis"},
            "provider": {"detected": True, "recommended_preset": "openai", "applied_preset": "openai"},
            "first_run": {"attempted": False, "status": "skipped"},
        }

    monkeypatch.setattr("aegis_code.cli.run_setup", _fake_run_setup)
    monkeypatch.setattr("aegis_code.cli.importlib.util.find_spec", lambda _name: None)
    exit_code = cli.main(["setup", "--yes"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Provider dependency missing:" in out
    assert "python -m pip install openai" in out


def test_setup_check_reports_key_source(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AEGIS_BASE_URL", raising=False)
    set_key("AEGIS_API_KEY", "aegis-secret", tmp_path, scope="global")
    set_key("AEGIS_BASE_URL", "https://base.example", tmp_path, scope="global")
    set_key("OPENAI_API_KEY", "openai-secret", tmp_path, scope="global")
    ensure = tmp_path / ".aegis"
    ensure.mkdir(parents=True, exist_ok=True)
    (ensure / "aegis-code.yml").write_text("providers:\n  enabled: true\n  provider: openai\n", encoding="utf-8")
    exit_code = cli.main(["setup", "--check"])
    out = capsys.readouterr().out
    assert exit_code in {0, 1}
    assert "- Aegis key: present (source: global)" in out
    assert "- Aegis base_url: https://base.example (source: global)" in out
    assert "- Provider key: present (source:" in out
    assert "- Provider key name: OPENAI_API_KEY" in out
