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


def test_report_includes_outside_allowed_targets_diagnostics(tmp_path: Path) -> None:
    payload = {
        "task": "fix tests",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 1, "top_level_directories": ["src"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 1},
        "final_failures": {"failed_tests": [], "failure_count": 1},
        "symptoms": [],
        "retry_policy": {"max_retries": 1, "allow_escalation": False, "retry_attempted": True, "retry_count": 1, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 1},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": [], "allowed_targets": ["src/calculator.py", "tests/test_calculator.py"]},
        "patch_diff": {
            "attempted": True,
            "available": False,
            "status": "blocked",
            "error": "outside_allowed_targets",
            "target_diagnostics": {
                "raw_edit_paths": ["src\\calculator.py"],
                "normalized_edit_paths": ["src/calculator.py"],
                "raw_allowed_targets": ["src/calculator.py", "tests/test_calculator.py"],
                "normalized_allowed_targets": ["src/calculator.py", "tests/test_calculator.py"],
                "validator_source": "structured_edits",
            },
        },
        "structured_patch": {"status": "failed", "failure_reason": "outside_allowed_targets"},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Failure reason: `outside_allowed_targets`" in content
    assert "Validator source: `structured_edits`" in content
    assert "Raw edit paths: `src\\calculator.py`" in content
    assert "Normalized edit paths: `src/calculator.py`" in content


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


def test_report_invalid_reason_sections_are_explicit(tmp_path: Path) -> None:
    payload = {
        "task": "x",
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
            "available": False,
            "status": "invalid",
            "error": "excessive_diff_size",
            "final_invalid_reason": "excessive_diff_size",
            "regeneration_trigger_reason": "syntactic_invalid",
            "invalid_diff_path": ".aegis/runs/latest.invalid.diff",
            "regeneration_attempted": True,
            "corrective_control_status": "applied",
            "regeneration": {
                "triggered": True,
                "reason": "syntactic_invalid",
                "trigger_reason": "syntactic_invalid",
                "attempt": 1,
                "result": "invalid",
                "regenerated_invalid_reason": "excessive_diff_size",
                "final_status": "invalid",
            },
        },
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Reason: `excessive_diff_size`" in content
    assert "## Patch Regeneration" in content
    assert "Reason: `syntactic_invalid`" in content
    assert "Regenerated invalid reason: `excessive_diff_size`" in content


def test_report_includes_provider_timeout_reason(tmp_path: Path) -> None:
    payload = {
        "task": "x",
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
            "available": False,
            "status": "unavailable",
            "error": "provider_timeout",
            "regeneration_attempted": True,
            "regeneration": {"triggered": True, "reason": "syntactic_invalid", "attempt": 1, "result": "timeout", "regenerated_invalid_reason": "provider_timeout"},
        },
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "provider_timeout" in content
    assert "Result: `timeout`" in content
    assert "Regenerated invalid reason: `provider_timeout`" in content


def test_report_renders_repair_diagnostics(tmp_path: Path) -> None:
    payload = {
        "task": "x",
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
            "repair_attempted": True,
            "repair_applied": False,
            "repair_status": "skipped",
            "repair_reason": "target_not_in_plan",
            "repair_error": None,
            "raw_repair_file_count": 4,
            "repair_file_count": 2,
            "repair_targets": ["src/helpers.py", "tests/test_helpers.py"],
        },
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Repair attempted: `True`" in content
    assert "Repair status: `skipped`" in content
    assert "Repair reason: `target_not_in_plan`" in content
    assert "Raw repair file count: `4`" in content
    assert "Repair file count: `2`" in content
    assert "Repair targets: `src/helpers.py, tests/test_helpers.py`" in content


def test_report_shows_task_too_vague_message(tmp_path: Path) -> None:
    payload = {
        "task": "add a new feature with tests",
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
        "patch_plan": {"strategy": "scope needed", "confidence": 0.5, "proposed_changes": [], "task_type": "vague_task"},
        "patch_diff": {
            "attempted": False,
            "available": False,
            "status": "skipped",
            "error": "task_too_vague",
            "reason": "task_too_vague",
            "regeneration_attempted": False,
        },
        "patch_quality": None,
        "status": "completed_tests_passed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Status: `skipped`" in content
    assert "task_too_vague" in content
    assert "Task needs clearer scope before patch generation." in content


def test_report_patch_diagnosis_section_includes_human_readable_fields(tmp_path: Path) -> None:
    payload = {
        "task": "add tests",
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
        "retry_policy": {"max_retries": 1, "allow_escalation": False, "retry_attempted": True, "retry_count": 1, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "append tests", "confidence": 0.7, "proposed_changes": [{"file": "tests/test_cli.py"}]},
        "patch_operation": {"operation": "append", "source": "cli"},
        "patch_diff": {
            "attempted": True,
            "available": False,
            "status": "blocked",
            "error": "append_output_invalid",
            "validation_result": {"summary": {"additions": 2, "deletions": 0}, "files": [{"new_path": "tests/test_cli.py"}]},
        },
        "patch_quality": None,
        "patch_safety": {"highest_severity": "warn", "issues": [{"file": "tests/test_cli.py", "type": "network_call", "message": "x", "line": 1}]},
        "guidance_hints": ["Try append-only mode"],
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "## Patch Diagnosis" in content
    assert "Patch status: `blocked`" in content
    assert "Patch error: `append_output_invalid`" in content
    assert "Patch operation: `append`" in content
    assert "Operation source: `cli`" in content
    assert "Files touched: `tests/test_cli.py`" in content
    assert "Additions/deletions: `+2 / -0`" in content
    assert "Safety severity: `WARN`" in content
    assert "Safety warnings count: `1`" in content
    assert "Retry attempted: `True`" in content
    assert "Retry count: `1`" in content
    assert "Guidance hints: `Try append-only mode`" in content


def test_report_files_touched_prefers_patch_diff_touched_files(tmp_path: Path) -> None:
    payload = {
        "task": "multi file",
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
        "retry_policy": {"max_retries": 1, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {
            "strategy": "feature",
            "confidence": 0.8,
            "proposed_changes": [{"file": "src/module.py"}, {"file": "tests/test_module.py"}],
        },
        "patch_diff": {
            "attempted": True,
            "available": True,
            "status": "generated",
            "touched_files": ["app/main.py", "tests/test_main.py", "README.md"],
            "validation_result": {"summary": {"additions": 10, "deletions": 2}, "files": [{"new_path": "app/main.py"}]},
        },
        "patch_quality": {"grounded": True, "relevant_files": True, "confidence": 0.9, "issues": []},
        "status": "completed_tests_passed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Files touched: `app/main.py, tests/test_main.py, README.md`" in content
    assert "src/module.py" not in content
    assert "tests/test_module.py" not in content


def test_report_patch_diagnosis_handles_no_append_needed(tmp_path: Path) -> None:
    payload = {
        "task": "add tests",
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
        "patch_plan": {"strategy": "append tests", "confidence": 0.7, "proposed_changes": [{"file": "tests/test_cli.py"}]},
        "patch_operation": {"operation": "append", "source": "cli"},
        "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "no_append_needed"},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Patch error: `no_append_needed`" in content


def test_report_patch_diagnosis_handles_append_syntax_invalid(tmp_path: Path) -> None:
    payload = {
        "task": "add tests",
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
        "patch_plan": {"strategy": "append tests", "confidence": 0.7, "proposed_changes": [{"file": "tests/test_cli.py"}]},
        "patch_operation": {"operation": "append", "source": "cli"},
        "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "append_syntax_invalid"},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Patch error: `append_syntax_invalid`" in content


def test_report_patch_diagnosis_handles_append_source_conflict(tmp_path: Path) -> None:
    payload = {
        "task": "add tests",
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
        "patch_plan": {"strategy": "append tests", "confidence": 0.7, "proposed_changes": [{"file": "tests/test_cli.py"}]},
        "patch_operation": {"operation": "append", "source": "cli"},
        "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "append_source_conflict"},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Patch error: `append_source_conflict`" in content
    assert "Operation source: `cli`" in content
    assert "Plan consistency: `skipped`" in content
    assert "tests/test_placeholder.py" not in content


def test_report_invalid_diff_preview_is_compact(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    long_diff = "\n".join([f"+line {i}" for i in range(60)]) + "\n"
    invalid_path = runs / "latest.invalid.diff"
    invalid_path.write_text(long_diff, encoding="utf-8")
    payload = {
        "task": "x",
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
        "patch_diff": {"attempted": True, "available": False, "status": "invalid", "error": "hunk_count_mismatch", "invalid_diff_path": ".aegis/runs/latest.invalid.diff"},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "Preview:" in content
    assert "... (20 more lines omitted)" in content


def test_report_renders_multi_file_feature_plan(tmp_path: Path) -> None:
    payload = {
        "task": "implement feature",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 2, "top_level_directories": ["src", "tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "bounded feature", "confidence": 0.7, "proposed_changes": []},
        "feature_plan": {
            "available": True,
            "kind": "phase1_planning",
            "steps": [
                {
                    "id": "step_1",
                    "target_file": "src/feature.py",
                    "operation": "replace",
                    "intent": "Implement feature logic.",
                    "max_changed_lines": 300,
                    "status": "planned",
                },
                {
                    "id": "step_2",
                    "target_file": "tests/test_feature.py",
                    "operation": "replace",
                    "intent": "Add regression tests.",
                    "max_changed_lines": 300,
                    "status": "planned",
                },
            ],
        },
        "patch_diff": {"attempted": False, "available": False, "status": "skipped", "error": None, "preview": ""},
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "## Multi-file Feature Plan" in content
    assert "step_1" in content
    assert "src/feature.py" in content
    assert "step_2" in content
    assert "tests/test_feature.py" in content


def test_report_renders_verification_diagnostics(tmp_path: Path) -> None:
    payload = {
        "task": "multi patch",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 3, "top_level_directories": ["app", "tests"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [{"file": "tests/test_main.py"}], "failure_count": 1},
        "final_failures": {"failed_tests": [{"file": "tests/test_main.py"}], "failure_count": 1},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [{"file": "tests/test_main.py"}], "failure_count": 1},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "multi", "confidence": 0.5, "proposed_changes": []},
        "patch_diff": {"attempted": False, "available": False, "status": "skipped", "error": None, "preview": ""},
        "verification": {"available": True, "test_command": "python -m pytest -q", "confidence": "high", "reason": "config"},
        "verification_diagnostics": {
            "command": "python -m pytest -q",
            "status": "failed",
            "exit_code": 1,
            "output": "ImportError: cannot import name X",
        },
        "patch_quality": None,
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "### Verification Diagnostics" in content
    assert "python -m pytest -q" in content
    assert "ImportError: cannot import name X" in content


def test_report_renders_policy_diagnostics_section(tmp_path: Path) -> None:
    payload = {
        "task": "add helper",
        "mode": "balanced",
        "dry_run": False,
        "budget": {"total": 1.0, "spent": 0.0, "remaining": 1.0},
        "aegis_execution": {},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
        "repo_scan": {"file_count": 1, "top_level_directories": ["app"]},
        "commands_run": [],
        "test_attempts": [],
        "initial_failures": {"failed_tests": [], "failure_count": 0},
        "final_failures": {"failed_tests": [], "failure_count": 0},
        "symptoms": [],
        "retry_policy": {"max_retries": 0, "allow_escalation": False, "retry_attempted": False, "retry_count": 0, "stopped_reason": "n/a"},
        "failures": {"failed_tests": [], "failure_count": 0},
        "failure_context": {"files": []},
        "sll_analysis": {"available": False},
        "patch_plan": {"strategy": "add helper", "confidence": 0.4, "proposed_changes": []},
        "patch_diff": {
            "attempted": True,
            "available": True,
            "status": "generated",
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "path": ".aegis/runs/latest.diff",
            "preview": "diff --git a/app/main.py b/app/main.py",
            "quality_score": 0.35,
            "issues": ["unrelated_files"],
            "policy_diagnostics": {
                "policy_checked": True,
                "policy_input_files": ["app/main.py"],
                "policy_input_length": 321,
                "policy_input_preview": "diff --git a/app/main.py b/app/main.py\n+def helper():\n+    return 1",
                "detected_project_stack": "python_pytest",
                "detected_js_project": False,
                "detected_node_test": False,
                "detected_additive_task": True,
                "detected_removed_public_symbols": [],
                "detected_docs_language_mismatch": False,
                "detected_readme_title_change": False,
                "final_policy_reason": None,
            },
        },
        "patch_quality": {"grounded": True, "relevant_files": True, "confidence": 0.35, "issues": ["unrelated_files"]},
        "status": "completed_tests_failed",
        "notes": [],
    }
    content = write_reports(payload, cwd=tmp_path)["md"].read_text(encoding="utf-8")
    assert "## Policy Diagnostics" in content
    assert "policy_checked: `True`" in content
    assert "policy_input_length: `321`" in content
    assert "policy_input_preview:" in content
    assert "```text" in content
    assert "diff --git a/app/main.py b/app/main.py" in content
    assert "detected_project_stack: `python_pytest`" in content
    assert "detected_additive_task: `True`" in content
