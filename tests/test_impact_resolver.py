from __future__ import annotations

from aegis_code.impact.resolver import extract_failure_signals, resolve_impact
from aegis_code.report import render_markdown_report
from aegis_code.runtime import _build_impact_payload


def test_generic_file_extraction() -> None:
    raw = "error in src/main.py\nfailing test tests/test_cli.py"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals
    assert signals[0].files == ["src/main.py", "tests/test_cli.py"]


def test_ignores_irrelevant_paths() -> None:
    raw = "node_modules/x.js .venv/lib.py .aegis/runs/latest.json __pycache__/m.py src/main.py"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].files == ["src/main.py"]


def test_import_error_js() -> None:
    raw = "Cannot find module './utils' at src/App.jsx"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].type == "import_error"


def test_import_error_python() -> None:
    raw = "ModuleNotFoundError: No module named foo"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].type == "import_error"


def test_name_error_js_reference_error() -> None:
    raw = "ReferenceError: foo is not defined in src/App.jsx"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].type == "name_error"


def test_assertion_failure_detection() -> None:
    raw = "expected 1 received 2"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].type == "assertion_failure"


def test_build_error_detection() -> None:
    raw = "failed to compile: SyntaxError in src/main.py"
    signals = extract_failure_signals(raw_output=raw, exit_code=1)
    assert signals[0].type == "build_error"


def test_impact_suggestion_from_test_file() -> None:
    signals = extract_failure_signals(raw_output="AssertionError in tests/test_cli.py", exit_code=1)
    report = resolve_impact(signals=signals, changed_files=[], repo_files=[], task="fix")
    assert report.suggestions
    assert "--file tests/test_cli.py" in str(report.suggestions[0].command)


def test_impact_suggestion_from_changed_files_fallback() -> None:
    report = resolve_impact(signals=[], changed_files=["src/main.py"], repo_files=[], task="fix")
    assert report.suggestions
    assert "--file src/main.py" in str(report.suggestions[0].command)


def test_multiple_files_command_uses_max_files_2() -> None:
    signals = extract_failure_signals(raw_output="AssertionError tests/test_a.py tests/test_b.py", exit_code=1)
    report = resolve_impact(signals=signals, changed_files=[], repo_files=[], task="fix")
    assert report.suggestions
    cmd = str(report.suggestions[0].command)
    assert "--file tests/test_a.py" in cmd
    assert "--file tests/test_b.py" in cmd
    assert "--max-files 2" in cmd


def test_verify_failure_report_integration_attaches_impact_section() -> None:
    impact = _build_impact_payload(
        commands_run=[{"full_output": "AssertionError in tests/test_cli.py", "exit_code": 1}],
        final_failures={"failure_count": 1, "failed_tests": [{"error": "AssertionError"}]},
        patch_diff={},
        structured_patch={},
        patch_plan={},
        failure_context={"files": [{"path": "tests/test_cli.py"}]},
        task="fix tests",
    )
    assert "summary" in impact
    assert "signals" in impact
    assert "suggestions" in impact

    payload = {
        "task": "fix tests",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["src", "tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 1},
        "final_failures": {"failed_tests": [], "failure_count": 1},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 1},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
        "patch_quality": None,
        "verification": {"available": True, "test_command": "npm test"},
        "status": "completed_tests_failed",
        "notes": [],
        "impact": impact,
    }
    md = render_markdown_report(payload)
    assert "## Impact Analysis" in md
    assert "Suggested next bounded patch" in md
