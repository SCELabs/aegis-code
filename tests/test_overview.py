from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli


def test_overview_no_budget_no_context_no_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code Overview" in out
    assert "Budget: not set" in out
    assert "Context: missing, 0 files, 0 chars" in out
    assert "Latest run: missing" in out
    assert "Backups: 0" in out


def test_overview_with_budget_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "budget.json").write_text(
        '{"limit": 2.0, "spent_estimate": 0.5, "currency": "USD", "events": []}',
        encoding="utf-8",
    )
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget: $1.50 / $2.00" in out


def test_overview_with_context_files(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("summary\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("constraints\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("architecture\n", encoding="utf-8")
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Context: available, 3 files" in out


def test_overview_runtime_mode_changes_under_low_budget(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "budget.json").write_text(
        '{"limit": 0.05, "spent_estimate": 0.0, "currency": "USD", "events": []}',
        encoding="utf-8",
    )
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Runtime mode: cheapest" in out
    assert "Runtime reason: low_budget" in out


def test_overview_latest_run_and_backups_count(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".aegis" / "backups" / "b1").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "backups" / "b2").mkdir(parents=True, exist_ok=True)
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Latest run: found" in out
    assert "Backups: 2" in out


def test_overview_read_only_no_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = {str(p.resolve()) for p in tmp_path.rglob("*")}
    exit_code = cli.main(["overview"])
    after = {str(p.resolve()) for p in tmp_path.rglob("*")}
    assert exit_code == 0
    assert before == after


def test_overview_shows_observed_capabilities(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "capabilities.json").write_text(
        json.dumps(
            {
                "version": 1,
                "detected_stack": "python",
                "package_manager": None,
                "selected_test_command": "pytest -q",
                "verification": {"available": True, "confidence": "high", "reason": "observed"},
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Observed capabilities: present" in out
    assert "Observed selected test command: pytest -q" in out
