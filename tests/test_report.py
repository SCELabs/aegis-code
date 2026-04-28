from __future__ import annotations

from pathlib import Path

from aegis_code.report import write_reports


def test_report_generation_writes_json_and_md(tmp_path: Path) -> None:
    payload = {
        "task": "example task",
        "mode": "balanced",
        "dry_run": True,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {"budget": {"pressure": "low"}},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["src", "tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": ["unstable_workflow"],
        "retry_policy": {
            "max_retries": 1,
            "allow_escalation": False,
            "retry_attempted": False,
            "retry_count": 0,
            "stopped_reason": "dry_run",
        },
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": None,
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {
            "attempted": False,
            "available": False,
            "provider": None,
            "model": None,
            "path": None,
            "error": None,
            "preview": "",
        },
        "patch_quality": None,
        "status": "dry_run_planned",
        "notes": ["planning only"],
    }
    paths = write_reports(payload, cwd=tmp_path)
    assert paths["json"].exists()
    assert paths["md"].exists()
    content = paths["md"].read_text(encoding="utf-8")
    assert "Aegis Code Run Report" in content
    assert "## Test Attempts" in content
    assert "## Retry Policy" in content
    assert "## Final Failure State" in content
    assert "## Structural Analysis" in content
    assert "## Proposed Fix Plan" in content
    assert "## Patch Diff Proposal" in content
    assert "## Patch Quality" not in content
    assert "Aegis Code runs a controlled execution loop with optional proposal-only patch diffs and deterministic patch-quality scoring." in content
    assert "Run `aegis-code --check-sll` to verify local setup" in content


def test_report_excludes_full_output_and_file_contents(tmp_path: Path) -> None:
    payload = {
        "task": "example task",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {"budget": {"pressure": "low"}},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["src", "tests"]},
        "commands_run": [
            {
                "name": "test",
                "command": "pytest -q",
                "status": "failed",
                "exit_code": 1,
                "full_output": "VERY_LONG_INTERNAL_OUTPUT",
            }
        ],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": ["unstable_workflow"],
        "retry_policy": {
            "max_retries": 1,
            "allow_escalation": False,
            "retry_attempted": False,
            "retry_count": 0,
            "stopped_reason": "dry_run",
        },
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {
            "files": [{"path": "tests/test_x.py", "content": "SENSITIVE_FILE_CONTENT_SHOULD_NOT_APPEAR"}]
        },
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {
            "attempted": True,
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "path": ".aegis/runs/latest.diff",
            "error": None,
            "preview": "diff --git a/x.py b/x.py\n" + ("+" * 2000),
        },
        "patch_quality": {
            "grounded": True,
            "relevant_files": True,
            "confidence": 0.9,
            "issues": [],
        },
        "status": "completed_tests_failed",
        "notes": ["planning only"],
    }
    paths = write_reports(payload, cwd=tmp_path)
    content = paths["md"].read_text(encoding="utf-8")
    assert "VERY_LONG_INTERNAL_OUTPUT" not in content
    assert "SENSITIVE_FILE_CONTENT_SHOULD_NOT_APPEAR" not in content
    assert ("+" * 1200) not in content
    assert "## Patch Quality" in content


def test_report_shows_available_sll_block_and_mapped_symptoms(tmp_path: Path) -> None:
    payload = {
        "task": "example task",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {"budget": {"pressure": "low"}},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["src", "tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": ["fragmented_output", "degenerate_loop"],
        "retry_policy": {
            "max_retries": 1,
            "allow_escalation": False,
            "retry_attempted": False,
            "retry_count": 0,
            "stopped_reason": "dry_run",
        },
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {
            "available": True,
            "regime": "chaotic",
            "collapse_risk": 0.7,
            "fragmentation_risk": 0.8,
            "drift_risk": 0.4,
            "stable_random_risk": 0.2,
        },
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {
            "attempted": False,
            "available": False,
            "provider": None,
            "model": None,
            "path": None,
            "error": None,
            "preview": "",
        },
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Regime: `chaotic`" in content
    assert "Collapse risk: `0.7`" in content
    assert "Mapped symptoms: `fragmented_output, degenerate_loop`" in content
