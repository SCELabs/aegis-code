from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.budget import can_spend, get_budget_state, load_budget, record_event, set_budget


def test_budget_set_creates_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["budget", "set", "1.5"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget set:" in out
    assert (tmp_path / ".aegis" / "budget.json").exists()


def test_budget_status_prints_values(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(2.0, cwd=tmp_path)
    exit_code = cli.main(["budget", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "limit=2.0" in out
    assert "spent_estimate=0.0" in out


def test_budget_clear_removes_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(2.0, cwd=tmp_path)
    assert (tmp_path / ".aegis" / "budget.json").exists()
    exit_code = cli.main(["budget", "clear"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget cleared." in out
    assert not (tmp_path / ".aegis" / "budget.json").exists()


def test_can_spend_false_when_limit_zero(tmp_path: Path) -> None:
    set_budget(0.0, cwd=tmp_path)
    assert can_spend("run_task", 0.01, cwd=tmp_path) is False


def test_main_task_skips_runtime_when_budget_exceeded(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(0.0, cwd=tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    exit_code = cli.main(["triage current test failures"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget limit reached. Skipping Aegis runtime." in out
    assert "Runtime Control:" not in out


def test_main_task_calls_runtime_when_budget_allows(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(1.0, cwd=tmp_path)
    called = {"run_task": False}

    def _fake_run_task(**_: object):
        called["run_task"] = True
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": True,
            "status": "dry_run_planned",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": False, "test_command": "n/a"},
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    assert exit_code == 0
    assert called["run_task"] is True


def test_fix_skips_runtime_when_budget_exceeded(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(0.0, cwd=tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget limit reached. Skipping Aegis runtime." in out


def test_budget_exceeded_skips_runtime_before_loading_context(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(0.0, cwd=tmp_path)
    monkeypatch.setattr(
        "aegis_code.cli.load_runtime_context",
        lambda **_: (_ for _ in ()).throw(AssertionError("context should not load")),
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    exit_code = cli.main(["x", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Budget limit reached. Skipping Aegis runtime." in out


def test_record_event_includes_selected_mode_and_reason(tmp_path: Path) -> None:
    set_budget(1.0, cwd=tmp_path)
    record_event("run_task", 0.01, cwd=tmp_path, selected_mode="cheapest", reason="low_budget")
    data = load_budget(cwd=tmp_path) or {}
    events = data.get("events", [])
    assert len(events) == 1
    assert events[0]["selected_mode"] == "cheapest"
    assert events[0]["reason"] == "low_budget"
    assert "timestamp" in events[0]


def test_record_event_works_without_optional_fields(tmp_path: Path) -> None:
    set_budget(1.0, cwd=tmp_path)
    record_event("run_task", 0.01, cwd=tmp_path)
    data = load_budget(cwd=tmp_path) or {}
    event = data.get("events", [])[0]
    assert event["operation"] == "run_task"
    assert event["estimated_cost"] == 0.01
    assert "selected_mode" not in event
    assert "reason" not in event


def test_low_budget_logs_cheapest_and_low_budget_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(0.05, cwd=tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "x",
            "mode": "cheapest",
            "dry_run": True,
            "status": "dry_run_planned",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": False, "test_command": "n/a"},
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    assert cli.main(["x", "--dry-run"]) == 0
    data = load_budget(cwd=tmp_path) or {}
    event = data.get("events", [])[0]
    assert event.get("selected_mode") == "cheapest"
    assert event.get("reason") == "low_budget"


def test_default_budget_case_logs_default_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(1.0, cwd=tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": True,
            "status": "dry_run_planned",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": False, "test_command": "n/a"},
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    assert cli.main(["x", "--dry-run"]) == 0
    data = load_budget(cwd=tmp_path) or {}
    event = data.get("events", [])[0]
    assert event.get("selected_mode") == "balanced"
    assert event.get("reason") == "default"


def test_get_budget_state_values(tmp_path: Path) -> None:
    state_missing = get_budget_state(cwd=tmp_path)
    assert state_missing["available"] is False
    assert state_missing["limit"] is None
    set_budget(1.0, cwd=tmp_path)
    record_event("run_task", 0.2, cwd=tmp_path)
    state = get_budget_state(cwd=tmp_path)
    assert state["available"] is True
    assert state["limit"] == 1.0
    assert state["spent_estimate"] == 0.2
    assert state["remaining_estimate"] == 0.8
