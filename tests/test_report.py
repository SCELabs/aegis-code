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
        "project_context": {"available": True, "included_paths": [".aegis/context/project_summary.md"], "total_chars": 123},
        "budget_state": {"available": True, "limit": 1.0, "spent_estimate": 0.2, "remaining_estimate": 0.8},
        "runtime_policy": {
            "requested_mode": "balanced",
            "selected_mode": "balanced",
            "reason": "default",
            "budget_present": True,
            "context_available": True,
        },
        "adapter": {
            "mode": "local",
            "aegis_client_available": False,
            "control_status": "fallback",
            "control_reason": "import_missing",
            "execution": "local",
            "mutation": "confirm_only",
            "fallback_reason": "import_missing",
            "error_type": None,
            "error_message": None,
        },
        "applied_aegis_guidance": {
            "model_tier_override": "cheap",
            "max_retries_applied": 1,
            "escalation_allowed": False,
            "context_mode": "minimal",
        },
        "status": "dry_run_planned",
        "notes": ["planning only"],
    }
    paths = write_reports(payload, cwd=tmp_path)
    assert paths["json"].exists()
    assert paths["md"].exists()
    content = paths["md"].read_text(encoding="utf-8")
    assert "Aegis Code Run Report" in content
    assert "## Test Attempts" in content
    assert "## Runtime Control" in content
    assert "Selected mode: `balanced`" in content
    assert "Reason: `default`" in content
    assert "Budget remaining: `$0.80`" in content
    assert "## Aegis Control" in content
    assert "Status: `fallback`" in content
    assert "Client available: `False`" in content
    assert "Reason: `import_missing`" in content
    assert "Execution: `local`" in content
    assert "Mutation: `confirm-only`" in content
    assert "Error type: `none`" in content
    assert "Error: `none`" in content
    assert "## Applied Aegis Guidance" in content
    assert "Model tier override: `cheap`" in content
    assert "Max retries applied: `1`" in content
    assert "Escalation allowed: `False`" in content
    assert "Context mode: `minimal`" in content
    assert "## Project Context" in content
    assert "Total chars: `123`" in content
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


def test_report_writes_history_snapshots(tmp_path: Path) -> None:
    payload = {"task": "history", "mode": "balanced", "dry_run": True}
    paths1 = write_reports(payload, cwd=tmp_path)
    paths2 = write_reports(payload, cwd=tmp_path)
    history_dir = tmp_path / ".aegis" / "runs" / "history"
    history_files = sorted(history_dir.glob("*.json"))
    assert paths1["json"].exists()
    assert paths1["md"].exists()
    assert paths1["history_json"].exists()
    assert paths2["history_json"].exists()
    assert len(history_files) == 2


def test_report_invalid_patch_shows_invalid_sections(tmp_path: Path) -> None:
    payload = {
        "task": "fix tests",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 1, "top_level_directories": ["tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {
            "attempted": True,
            "available": False,
            "status": "invalid",
            "error": "hunk_count_mismatch",
            "invalid_diff_path": ".aegis/runs/latest.invalid.diff",
            "regeneration_attempted": True,
            "corrective_control_status": "no_guidance_returned",
            "regeneration": {"triggered": True, "reason": "invalid_diff", "final_status": "invalid"},
        },
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Status: `invalid`" in content
    assert "Invalid diff path: `.aegis/runs/latest.invalid.diff`" in content
    assert "Diff failed validation and cannot be applied." in content
    assert "Patch quality: invalid (not evaluated)" in content
    assert "Aegis corrective control: `no_guidance_returned`" in content


def test_report_key_usage_metadata_has_no_values(tmp_path: Path) -> None:
    payload = {
        "task": "x",
        "mode": "balanced",
        "dry_run": True,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 1, "top_level_directories": []},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "dry_run"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {"attempted": False, "available": False},
        "patch_quality": None,
        "key_usage": [
            {"name": "OPENAI_API_KEY", "source": "env", "used_for": "provider_openai", "present": True},
            {"name": "AEGIS_API_KEY", "source": "global", "used_for": "aegis_control", "present": True},
        ],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "## Key Usage" in content
    assert "OPENAI_API_KEY" in content
    assert "provider_openai" in content
    assert "secret" not in content.lower()


def test_report_includes_plan_consistency_section(tmp_path: Path) -> None:
    payload = {
        "task": "add feature",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 1, "top_level_directories": ["src"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {
            "attempted": True,
            "available": True,
            "status": "generated",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "path": ".aegis/runs/latest.diff",
            "preview": "diff --git a/src/main.py b/src/main.py\n",
            "plan_consistent": False,
            "plan_missing_targets": ["src/helpers.py"],
        },
        "patch_quality": {"grounded": True, "relevant_files": True, "confidence": 0.5, "issues": []},
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "## Plan Consistency" in content
    assert "Consistent: `False`" in content
    assert "src/helpers.py" in content
