from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli


def test_status_no_latest_run(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert 'No latest run found. Run aegis-code "<task>" first.' in out


def test_status_with_full_fields(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True)
    payload = {
        "task": "triage failures",
        "status": "completed_tests_failed",
        "failures": {"failure_count": 2, "failed_tests": []},
        "verification": {
            "available": True,
            "test_command": "python -m pytest -q",
            "command": "python -m pytest -q",
            "source": "capabilities",
            "observed": True,
            "detected_stack": "python",
        },
        "sll_analysis": {"available": True, "regime": "fragmentation"},
        "patch_diff": {"attempted": True, "available": True, "path": ".aegis/runs/latest.diff"},
        "patch_quality": {"confidence": 0.8},
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    backup = tmp_path / ".aegis" / "backups" / "20260428_143210" / "aegis_code" / "runtime.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text("x\n", encoding="utf-8")

    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "triage failures" in out
    assert "completed_tests_failed" in out
    assert "Failure count: 2" in out
    assert "Verification:" in out
    assert "command: python -m pytest -q" in out
    assert "source: capabilities" in out
    assert "observed: true" in out
    assert "available=True regime=fragmentation" in out
    assert "attempted=True available=True" in out
    assert "Patch quality confidence: 0.8" in out
    assert "Backup count: 1" in out


def test_status_with_missing_optional_fields(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True)
    payload = {"task": "x", "status": "completed", "failures": {"failure_count": 0}}
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verification:" in out
    assert "command: python -m pytest -q" in out
    assert "Patch quality confidence: n/a" in out
    assert "Backup count: 0" in out


def test_status_uses_latest_verification_when_present(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True)
    payload = {
        "task": "x",
        "status": "completed",
        "failures": {"failure_count": 0},
        "verification": {
            "available": False,
            "test_command": "custom test",
            "source": "config",
            "observed": False,
            "detected_stack": "custom",
        },
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verification:" in out
    assert "command: custom test" in out
    assert "source: config" in out


def test_status_does_not_run_runtime(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True)
    (runs / "latest.json").write_text(
        json.dumps({"task": "x", "status": "completed", "failures": {"failure_count": 0}}),
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Status:" in out


def test_status_shows_provider_name_and_base_url(tmp_path: Path, monkeypatch, capsys) -> None:
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
    runs = aegis / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps({"task": "x", "status": "completed", "failures": {"failure_count": 0}}), encoding="utf-8")
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Provider:" in out
    assert "name: openai-compatible" in out
    assert "base_url: http://localhost:11434/v1" in out


def test_status_openai_provider_shows_default_base_url_label(tmp_path: Path, monkeypatch, capsys) -> None:
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
    runs = aegis / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps({"task": "x", "status": "completed", "failures": {"failure_count": 0}}), encoding="utf-8")
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Provider:" in out
    assert "name: openai" in out
    assert "base_url: default OpenAI API" in out
