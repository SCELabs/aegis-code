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
        "verification": {"available": True, "test_command": "python -m pytest -q", "detected_stack": "python"},
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
    assert "Verification: available=True command=python -m pytest -q stack=python" in out
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

    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verification: available=False command=n/a stack=n/a" in out
    assert "Patch quality confidence: n/a" in out
    assert "Backup count: 0" in out


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
