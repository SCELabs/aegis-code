from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.next_actions import build_next_actions, format_next_actions


def test_patch_available_next_action() -> None:
    data = build_next_actions({"patch_diff": {"available": True}})
    text = format_next_actions(data)
    assert "Next safe action:" in text
    assert "1. Inspect: aegis-code diff --stat" in text
    assert "2. Validate: aegis-code apply --check" in text
    assert "3. Apply safely: aegis-code apply --confirm --run-tests" in text


def test_blocked_low_patch_next_action() -> None:
    data = build_next_actions({"patch_diff": {"available": True, "apply_safety": "LOW"}})
    text = format_next_actions(data)
    assert "1. Do not apply this patch yet." in text
    assert "2. Inspect why: aegis-code apply --check" in text
    assert "3. Regenerate carefully: aegis-code fix --max-cycles 1" in text


def test_no_verification_next_action() -> None:
    data = build_next_actions({"verification": {"available": False}})
    text = format_next_actions(data)
    assert "1. Probe project capabilities: aegis-code probe --run" in text
    assert "2. Or set commands.test in .aegis/aegis-code.yml" in text


def test_tests_failed_next_action() -> None:
    data = build_next_actions(
        {
            "status": "completed_tests_failed",
            "final_failures": {"failure_count": 2},
            "verification": {"available": True},
        }
    )
    text = format_next_actions(data)
    assert "1. Inspect failures: aegis-code report" in text
    assert "2. Generate bounded fix: aegis-code fix --max-cycles 1" in text
    assert "3. Apply only after check: aegis-code apply --check" in text


def test_budget_skipped_next_action() -> None:
    data = build_next_actions({"status": "budget_skipped"})
    text = format_next_actions(data)
    assert "1. Check budget: aegis-code budget status" in text
    assert "2. Raise or clear budget if appropriate: aegis-code budget set <amount>" in text


def test_default_fallback_next_action() -> None:
    data = build_next_actions({"verification": {"available": True}})
    text = format_next_actions(data)
    assert "1. Review report: aegis-code report" in text
    assert "2. Check project status: aegis-code status" in text


def test_environment_issues_next_action_priority() -> None:
    data = build_next_actions(
        {
            "environment_issues": [
                {
                    "warning": "Python 3.14 may lack prebuilt wheels for some native dependencies.",
                    "suggestion": "Use Python 3.11 or 3.12 for best compatibility.",
                }
            ],
            "verification": {"available": False},
        }
    )
    text = format_next_actions(data)
    assert "1. Resolve environment issues listed above" in text
    assert "2. Re-run: aegis-code doctor" in text
    assert "3. Then run: aegis-code probe --run" in text


def test_environment_issues_override_probe_and_tests_suggestions() -> None:
    data = build_next_actions(
        {
            "environment_issues": [{"warning": "x", "suggestion": "y"}],
            "status": "completed_tests_failed",
            "final_failures": {"failure_count": 3},
            "verification": {"available": False},
        }
    )
    assert data.get("rule") == "environment_issues"
    text = format_next_actions(data)
    assert "Resolve environment issues listed above" in text
    assert "Inspect failures: aegis-code report" not in text
    assert "Probe project capabilities: aegis-code probe --run" not in text


def test_no_environment_issues_uses_normal_behavior() -> None:
    data = build_next_actions({"verification": {"available": False}})
    assert data.get("rule") == "no_verification"
    text = format_next_actions(data)
    assert "Probe project capabilities: aegis-code probe --run" in text


def test_status_output_includes_next_safe_action(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "x",
        "status": "completed_tests_passed",
        "failures": {"failure_count": 0},
        "final_failures": {"failure_count": 0},
        "verification": {"available": True, "test_command": "python -m pytest -q", "detected_stack": "python"},
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    exit_code = cli.main(["status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Next safe action:" in out
