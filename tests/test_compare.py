from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.compare import build_comparison, format_comparison, load_last_runs


def _write_run(path: Path, name: str, payload: dict[str, object]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_compare_no_runs_case(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["compare"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No runs found" in out


def test_compare_single_run_case(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    _write_run(runs, "latest.json", {"status": "x"})
    exit_code = cli.main(["compare"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Only one run found" in out


def test_compare_two_runs_detects_changes(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    prev = {
        "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        "selected_model_tier": "mid",
        "retry_policy": {"max_retries": 2, "allow_escalation": True},
        "applied_aegis_guidance": {"context_mode": "balanced"},
        "adapter": {"mode": "local"},
    }
    current = {
        "runtime_policy": {"selected_mode": "cheapest", "reason": "low_budget"},
        "selected_model_tier": "cheap",
        "retry_policy": {"max_retries": 1, "allow_escalation": False},
        "applied_aegis_guidance": {"context_mode": "minimal"},
        "adapter": {"mode": "aegis"},
    }
    _write_run(runs, "20260428_120000.json", prev)
    _write_run(runs, "latest.json", current)

    exit_code = cli.main(["compare"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Changed fields:" in out
    assert "runtime_control.selected_mode: balanced -> cheapest" in out
    assert "runtime_control.reason: default -> low_budget" in out
    assert "model_tier: mid -> cheap" in out
    assert "max_retries: 2 -> 1" in out
    assert "escalation: True -> False" in out
    assert "context_mode: balanced -> minimal" in out
    assert "adapter.mode: local -> aegis" in out
    assert "runtime_control.reason: low_budget" in out


def test_compare_uses_history_last_two_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    history = tmp_path / ".aegis" / "runs" / "history"
    oldest = {"runtime_policy": {"selected_mode": "balanced", "reason": "default"}, "selected_model_tier": "mid", "retry_policy": {"max_retries": 2, "allow_escalation": True}, "applied_aegis_guidance": {"context_mode": "balanced"}, "adapter": {"mode": "local"}}
    prev = {"runtime_policy": {"selected_mode": "balanced", "reason": "default"}, "selected_model_tier": "mid", "retry_policy": {"max_retries": 1, "allow_escalation": True}, "applied_aegis_guidance": {"context_mode": "balanced"}, "adapter": {"mode": "local"}}
    current = {"runtime_policy": {"selected_mode": "cheapest", "reason": "low_budget"}, "selected_model_tier": "cheap", "retry_policy": {"max_retries": 1, "allow_escalation": False}, "applied_aegis_guidance": {"context_mode": "minimal"}, "adapter": {"mode": "aegis"}}
    _write_run(history, "20260428_100000_000001.json", oldest)
    _write_run(history, "20260428_100000_000002.json", prev)
    _write_run(history, "20260428_100000_000003.json", current)
    _write_run(tmp_path / ".aegis" / "runs", "latest.json", {"runtime_policy": {"selected_mode": "premium"}})

    exit_code = cli.main(["compare"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "runtime_control.selected_mode: balanced -> cheapest" in out
    assert "runtime_control.reason: default -> low_budget" in out
    assert "adapter.mode: local -> aegis" in out
    assert "premium" not in out


def test_build_comparison_field_mapping() -> None:
    prev = {
        "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        "selected_model_tier": "mid",
        "retry_policy": {"max_retries": 1, "allow_escalation": False},
        "applied_aegis_guidance": {"context_mode": "balanced"},
        "adapter": {"mode": "local"},
    }
    current = {
        "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        "selected_model_tier": "mid",
        "retry_policy": {"max_retries": 1, "allow_escalation": False},
        "applied_aegis_guidance": {"context_mode": "balanced"},
        "adapter": {"mode": "local"},
    }
    data = build_comparison(prev, current)
    assert data["fields"]["adapter.mode"] == ("local", "local")
    assert data["changes"] == {}


def test_compare_detects_reason_change() -> None:
    prev = {"runtime_policy": {"selected_mode": "balanced", "reason": "default"}}
    current = {"runtime_policy": {"selected_mode": "cheapest", "reason": "low_budget"}}
    data = build_comparison(prev, current)
    assert data["changes"]["runtime_control.reason"] == {"from": "default", "to": "low_budget"}
    rendered = format_comparison(data)
    assert "runtime_control.reason: default -> low_budget" in rendered
    assert "runtime_control.reason: low_budget" in rendered


def test_compare_reason_missing_is_safe() -> None:
    prev = {"runtime_policy": {"selected_mode": "balanced"}}
    current = {"runtime_policy": {"selected_mode": "balanced", "reason": "default"}}
    data = build_comparison(prev, current)
    assert data["fields"]["runtime_control.reason"] == ("n/a", "default")


def test_load_last_runs_prefers_latest_json(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    _write_run(runs, "20260428_110000.json", {"task": "prev"})
    _write_run(runs, "latest.json", {"task": "current"})
    prev, current = load_last_runs(tmp_path)
    assert prev is not None and prev["task"] == "prev"
    assert current is not None and current["task"] == "current"


def test_load_last_runs_uses_history_when_available(tmp_path: Path) -> None:
    history = tmp_path / ".aegis" / "runs" / "history"
    _write_run(history, "20260428_110000_000001.json", {"task": "prev"})
    _write_run(history, "20260428_110000_000002.json", {"task": "current"})
    _write_run(tmp_path / ".aegis" / "runs", "latest.json", {"task": "latest_only"})
    prev, current = load_last_runs(tmp_path)
    assert prev is not None and prev["task"] == "prev"
    assert current is not None and current["task"] == "current"
