from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli


def test_usage_command_with_data(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    usage_path = tmp_path / ".aegis" / "usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps(
            {
                "calls": 3,
                "successful": 2,
                "fallbacks": 1,
                "actions_applied": 7,
                "last_used": "2026-04-29T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["usage"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Aegis Usage:" in out
    assert "- Attempts: 3" in out
    assert "- Successful: 2" in out
    assert "- Fallbacks: 1" in out
    assert "- Actions applied: 7" in out
    assert "- Last used: 2026-04-29T12:00:00Z" in out


def test_usage_command_no_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["usage"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "No Aegis usage recorded yet." in out


def test_usage_command_warning_approaching(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    usage_path = tmp_path / ".aegis" / "usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps(
            {
                "calls": 95,
                "successful": 80,
                "fallbacks": 15,
                "actions_applied": 120,
                "last_used": "2026-04-29T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["usage"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "⚠ Approaching Aegis usage limit (100 calls)" in out


def test_usage_command_warning_reached(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    usage_path = tmp_path / ".aegis" / "usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(
        json.dumps(
            {
                "calls": 100,
                "successful": 82,
                "fallbacks": 18,
                "actions_applied": 123,
                "last_used": "2026-04-29T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(["usage"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "⚠ Aegis usage limit reached (100 calls)" in out
    assert "Aegis will continue to run, but limits may apply in future versions." in out
