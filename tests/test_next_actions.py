from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.next_actions import build_next_actions


def _write_latest(tmp_path: Path, payload: dict) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_next_suggests_init_when_config_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert "aegis-code init" in commands


def test_next_suggests_context_refresh_when_context_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text("commands:\n  test: \"python -m pytest -q\"\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert "aegis-code context refresh" in commands


def test_next_suggests_run_when_no_latest_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("x\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("x\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("x\n", encoding="utf-8")

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert 'aegis-code "<task>"' in commands


def test_next_suggests_fix_when_failures_exist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("x\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("x\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("x\n", encoding="utf-8")
    _write_latest(tmp_path, {"failures": {"failure_count": 2}})

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert "aegis-code fix" in commands


def test_next_suggests_apply_check_when_patch_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("x\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("x\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("x\n", encoding="utf-8")
    _write_latest(
        tmp_path,
        {
            "failures": {"failure_count": 0},
            "patch_diff": {"available": True, "path": ".aegis/runs/latest.diff"},
        },
    )

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert "aegis-code apply --check .aegis/runs/latest.diff" in commands


def test_next_includes_budget_low_signal(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    aegis = tmp_path / ".aegis"
    aegis.mkdir(parents=True, exist_ok=True)
    (aegis / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (aegis / "budget.json").write_text(
        json.dumps({"limit": 1.0, "spent_estimate": 0.95, "currency": "USD", "events": []}),
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    context_dir = aegis / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("x\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("x\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("x\n", encoding="utf-8")
    _write_latest(tmp_path, {"failures": {"failure_count": 0}, "patch_diff": {"available": False}})

    data = build_next_actions(tmp_path)

    commands = [item["command"] for item in data["actions"]]
    assert "aegis-code budget status" in commands


def test_cli_next_outputs_suggestions(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = cli.main(["next"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "Suggested next actions:" in out
    assert "Signals:" in out
