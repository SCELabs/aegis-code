from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.budget import set_budget
from aegis_code.policy import format_runtime_control_summary, select_runtime_mode


def test_policy_status_no_budget_no_context(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["policy", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Runtime policy status:" in out
    assert "exists: False" in out
    assert "available: False" in out


def test_policy_status_with_budget_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    set_budget(2.0, cwd=tmp_path)
    exit_code = cli.main(["policy", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "exists: True" in out
    assert "limit: 2.0" in out
    assert "spent_estimate: 0.0" in out
    assert "remaining_estimate: 2.0" in out


def test_policy_status_with_context_files(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis" / "context").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "context" / "project_summary.md").write_text("summary\n", encoding="utf-8")
    (tmp_path / ".aegis" / "context" / "constraints.md").write_text("constraints\n", encoding="utf-8")
    (tmp_path / ".aegis" / "context" / "architecture.md").write_text("architecture\n", encoding="utf-8")
    exit_code = cli.main(["policy", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "available: True" in out
    assert ".aegis/context/project_summary.md" in out


def test_policy_status_includes_models_provider_and_verification_no_secret(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value-should-not-print")
    exit_code = cli.main(["policy", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "cheap:" in out and "mid:" in out and "premium:" in out
    assert "enabled:" in out and "name:" in out and "api_key_env:" in out
    assert "commands.test:" in out
    assert "secret-value-should-not-print" not in out


def test_policy_status_read_only_no_writes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = {str(p.resolve()) for p in tmp_path.rglob("*")}
    exit_code = cli.main(["policy", "status"])
    after = {str(p.resolve()) for p in tmp_path.rglob("*")}
    assert exit_code == 0
    assert before == after


def test_policy_missing_subcommand_exits_nonzero(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["policy"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "aegis-code policy" in out


def test_select_runtime_mode_no_budget_keeps_mode(tmp_path: Path) -> None:
    assert select_runtime_mode("balanced", cwd=tmp_path) == "balanced"


def test_select_runtime_mode_with_budget_enough_keeps_mode(tmp_path: Path) -> None:
    set_budget(1.0, cwd=tmp_path)
    assert select_runtime_mode("balanced", cwd=tmp_path) == "balanced"


def test_select_runtime_mode_low_remaining_forces_cheapest(tmp_path: Path) -> None:
    set_budget(0.05, cwd=tmp_path)
    assert select_runtime_mode("balanced", cwd=tmp_path) == "cheapest"


def test_format_runtime_control_summary_low_budget_case() -> None:
    text = format_runtime_control_summary(
        {"selected_mode": "cheapest", "reason": "low_budget"},
        {"available": True, "remaining_estimate": 0.08},
        {"available": True},
    )
    assert "Selected mode: cheapest" in text
    assert "Reason: low_budget" in text
    assert "Budget remaining: $0.08 (control signal)" in text
    assert "Budget affects runtime mode selection, not actual API cost." in text
    assert "Context available: true" in text


def test_format_runtime_control_summary_default_case() -> None:
    text = format_runtime_control_summary(
        {"selected_mode": "balanced", "reason": "default"},
        {"available": True, "remaining_estimate": 1.0},
        {"available": True},
    )
    assert "Selected mode: balanced" in text
    assert "Reason: default" in text
    assert "Budget remaining: $1.00 (control signal)" in text
    assert "Budget affects runtime mode selection, not actual API cost." in text


def test_format_runtime_control_summary_no_budget_no_context() -> None:
    text = format_runtime_control_summary(
        {"selected_mode": "balanced", "reason": "default"},
        {"available": False},
        {"available": False},
    )
    assert "Budget: not set" in text
    assert "Context available: false" in text
