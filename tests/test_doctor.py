from __future__ import annotations

from pathlib import Path

from aegis_code import cli


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
