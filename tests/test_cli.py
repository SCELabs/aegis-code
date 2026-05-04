from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.budget import load_budget
from aegis_code.models import AegisDecision, CommandResult


class FakeAegisClient:
    def step_scope(self, **_: object) -> AegisDecision:
        return AegisDecision(
            model_tier="cheap",
            context_mode="focused",
            max_retries=1,
            allow_escalation=False,
            execution={"budget": {"pressure": "low"}},
            note="fake",
        )


def test_cli_init_creates_project_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    exit_code = cli.main(["init"])
    assert exit_code == 0
    assert (tmp_path / ".aegis" / "aegis-code.yml").exists()
    assert (tmp_path / ".aegis" / "project_model.md").exists()
    config_text = (tmp_path / ".aegis" / "aegis-code.yml").read_text(encoding="utf-8")
    assert 'test: "python -m pytest -q"' in config_text


def test_cli_init_does_not_overwrite_existing_config_without_force(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir()
    cfg = tmp_path / ".aegis" / "aegis-code.yml"
    cfg.write_text("mode: balanced\nbudget_per_task: 1.0\ncommands:\n  test: \"custom test\"\n", encoding="utf-8")
    exit_code = cli.main(["init"])
    assert exit_code == 0
    assert "custom test" in cfg.read_text(encoding="utf-8")


def test_cli_dry_run_writes_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.runtime.client_from_env", lambda _base_url: FakeAegisClient())
    exit_code = cli.main(["plan release notes", "--dry-run"])
    assert exit_code == 0
    assert (tmp_path / ".aegis" / "runs" / "latest.json").exists()
    assert (tmp_path / ".aegis" / "runs" / "latest.md").exists()


def test_cli_accepts_propose_patch_flag(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.runtime.client_from_env", lambda _base_url: FakeAegisClient())
    exit_code = cli.main(["plan release notes", "--dry-run", "--propose-patch"])
    assert exit_code == 0


def test_cli_check_sll_does_not_run_runtime(monkeypatch) -> None:
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    monkeypatch.setattr("aegis_code.cli.check_sll_available", lambda: {"available": False, "import_path": "structural_language_lab", "error": "x"})
    exit_code = cli.main(["--check-sll"])
    assert exit_code == 0


def test_cli_omits_patch_quality_when_not_present(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.runtime.client_from_env", lambda _base_url: FakeAegisClient())
    exit_code = cli.main(["plan release notes", "--dry-run", "--no-report"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Patch quality:" not in out


def test_help_mentions_key_commands(capsys) -> None:
    exit_code = cli.main([])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "aegis-code" in out


def test_task_passes_project_context_to_runtime(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    captured = {"context": None, "budget_state": None, "runtime_policy": None}

    def _fake_context(**_: object):
        return {"available": True, "files": {}, "included_paths": [".aegis/context/project_summary.md"], "total_chars": 42}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["context"] = options.project_context
        captured["budget_state"] = options.budget_state
        captured["runtime_policy"] = options.runtime_policy
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

    monkeypatch.setattr("aegis_code.cli.load_runtime_context", _fake_context)
    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    assert exit_code == 0
    assert captured["context"] is not None
    assert captured["context"]["available"] is True
    assert isinstance(captured["budget_state"], dict)
    assert isinstance(captured["runtime_policy"], dict)


def test_task_low_budget_forces_cheapest_mode(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "budget.json").write_text(
        '{"limit": 0.05, "spent_estimate": 0.0, "currency": "USD", "events": []}',
        encoding="utf-8",
    )
    captured = {"mode": None}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["mode"] = options.mode
        return {
            "task": "x",
            "mode": options.mode,
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
    out = capsys.readouterr().out
    assert exit_code == 0
    assert captured["mode"] == "cheapest"
    assert "Selected runtime mode: cheapest" in out


def test_task_runtime_event_includes_selected_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "budget.json").write_text(
        '{"limit": 1.0, "spent_estimate": 0.0, "currency": "USD", "events": []}',
        encoding="utf-8",
    )

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


def test_task_prints_runtime_control_summary_when_runtime_runs(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

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
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {
                "mode": "local",
                "aegis_client_available": False,
                "fallback_reason": "import_missing",
                "error_type": None,
                "error_message": None,
            },
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Runtime Control:" in out
    assert "Aegis Control:" in out
    assert "Execution: local" in out


def test_task_prints_runtime_adapter_error_fields(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

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
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {
                "mode": "local",
                "aegis_client_available": True,
                "fallback_reason": "client_error",
                "error_type": "RuntimeError",
                "error_message": "boom",
            },
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Error type: RuntimeError" in out
    assert "Error: boom" in out


def test_task_prints_task_driven_patch_note(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "implement notes cli",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": [{}]},
            "patch_diff": {"attempted": True, "available": False, "error": "Provider unavailable"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {
                "mode": "local",
                "aegis_client_available": False,
                "fallback_reason": "disabled",
                "error_type": None,
                "error_message": None,
            },
            "task_driven_patch_proposal": True,
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["implement notes cli", "--propose-patch"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch proposal generated from task intent (no test failures)." in out


def test_task_prints_invalid_patch_status_and_quality_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": [{}]},
            "patch_diff": {
                "attempted": True,
                "available": False,
                "status": "invalid",
                "error": "hunk_count_mismatch",
                "invalid_diff_path": ".aegis/runs/latest.invalid.diff",
                "regeneration_attempted": True,
                "corrective_control_status": "no_guidance_returned",
            },
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--propose-patch"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch diff status: invalid" in out
    assert "Patch quality: invalid (not evaluated)" in out
    assert "Aegis corrective control: no_guidance_returned" in out
    assert "Aegis Code Summary" in out
    assert "Status: BLOCKED" in out
    assert "Reason: hunk_count_mismatch" in out


def test_progress_messages_emitted_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("running verification command: python -m pytest -q")
            cb("generating provider diff with openai:gpt-4.1-mini")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[1/" in out
    assert "running verification command" in out


def test_provider_heartbeat_non_tty_sparse_updates(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("generating provider diff with openai:gpt-4.1-mini")
            cb("  waiting on provider for patch generation... (2s)")
            cb("  waiting on provider for patch generation... (4s)")
            cb("  waiting on provider for patch generation... (10s)")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "waiting on provider" in out or "generating provider diff" in out
    assert "[2/" not in out


def test_diff_command_no_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["diff"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No diff found. Run a task first." in out


def test_diff_command_stat(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (runs / "latest.diff").write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["diff", "--stat"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Diff: .aegis/runs/latest.diff" in out
    assert "Files:" in out
    assert "src/main.py (+1 -1)" in out


def test_task_final_summary_valid_patch_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    diff_path = runs / "latest.diff"
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("x=1\n", encoding="utf-8")
    diff_path.write_text(
        "diff --git a/tests/test_cli.py b/tests/test_cli.py\n"
        "--- a/tests/test_cli.py\n"
        "+++ b/tests/test_cli.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )

    def _fake_run_task(**_: object):
        return {
            "task": "add tests only for existing behavior",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": [{}]},
            "patch_diff": {
                "attempted": True,
                "available": True,
                "status": "generated",
                "path": str(diff_path),
                "validation_result": {"valid": True},
                "syntactic_valid": True,
                "plan_consistent": True,
                "repair_applied": True,
            },
            "patch_quality": {"confidence": 0.9},
            "apply_safety": "HIGH",
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["add tests only for existing behavior", "--propose-patch"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Code Summary" in out
    assert "Status: completed_tests_passed" in out
    assert "Patch:" in out
    assert "- Safety: HIGH" in out
    assert "Files:" in out
    assert "- tests/test_cli.py (+1 -1)" in out


def test_apply_with_run_tests_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff_file = tmp_path / "latest.diff"
    diff_file.write_text("diff --git a/x b/x\n", encoding="utf-8")

    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda _path, cwd=None: {
            "applied": True,
            "path": str(diff_file),
            "files_changed": [{"path": "src/main.py", "backup_path": None, "additions": 1, "deletions": 0, "created": False}],
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda _cmd, cwd=None: CommandResult(
            name="tests",
            command=_cmd,
            status="ok",
            exit_code=0,
            stdout="",
            stderr="",
            output_preview="",
            full_output="",
        ),
    )
    exit_code = cli.main(["apply", str(diff_file), "--confirm", "--run-tests"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Verification:" in out
    assert "- Tests: passed" in out


def test_provider_heartbeat_tty_uses_carriage_return(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("generating provider diff with openai:gpt-4.1-mini")
            cb("  waiting on provider for patch generation... (12s)")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "\r[1/" in out
    assert "waiting 12s" in out


def test_provider_heartbeat_completion_emits_newline(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("generating provider diff with openai:gpt-4.1-mini")
            cb("  waiting on provider for patch generation... (2s)")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "\nAegis Code: controlled execution" in out


def test_provider_slow_warning_uses_override_timeout_value(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("generating provider diff with openai:gpt-4.1-mini")
            cb("  provider is slow; timeout at 30s")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--provider-timeout", "30"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "provider is slow; timeout at 30s" in out


def test_quiet_suppresses_progress_messages(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("running verification command: python -m pytest -q")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--quiet"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "[1/" not in out
    assert "waiting on provider" not in out


def test_progress_output_has_no_secret_values(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    secret = "super-secret-value"

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        cb = getattr(options, "progress_callback", None)
        if callable(cb):
            cb("resolving keys")
            cb("generating provider diff with openai:gpt-4.1-mini")
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert secret not in out


def test_cli_provider_timeout_override_passed_to_task_options(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        captured["options"] = kwargs["options"]
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--provider-timeout", "42"])
    assert exit_code == 0
    options = captured.get("options")
    assert options is not None
    assert getattr(options, "provider_timeout_seconds", None) == 42


def test_diff_command_invalid_diff_preview(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.invalid.diff").write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["diff"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Status: BLOCKED" in out
    assert "Showing invalid diff:" in out
    assert "This patch was not accepted and cannot be applied." in out
    assert "diff --git a/src/main.py b/src/main.py" in out


def test_diff_command_invalid_diff_full(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    full_text = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-x = 1\n"
        "+x = 2\n"
    )
    (runs / "latest.invalid.diff").write_text(full_text, encoding="utf-8")
    exit_code = cli.main(["diff", "--full"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Status: BLOCKED" in out
    assert "This patch was not accepted and cannot be applied." in out
    assert full_text.strip() in out


def test_diff_command_invalid_diff_stat(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.invalid.diff").write_text(
        "not a unified diff\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["diff", "--stat"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Status: BLOCKED" in out
    assert "Reason: invalid_diff" in out
    assert "File stats unavailable for invalid diff." in out
    assert "Run `aegis-code diff --full` to inspect raw provider output." in out


def test_task_output_shows_sll_regime_and_risk_when_available(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_passed",
            "failures": {"failure_count": 0},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": False, "available": False, "status": "skipped"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "sll_pre_call": {"available": True, "regime": "boundary"},
            "sll_post_call": {"available": False},
            "sll_risk": "watch",
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SLL:" in out
    assert "- regime: boundary" in out
    assert "- risk: watch" in out


def test_task_output_shows_sll_fix_guidance_when_regeneration_attempted(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        return {
            "task": "x",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "invalid", "regeneration_attempted": True},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "sll_pre_call": {"available": False},
            "sll_post_call": {"available": True, "regime": "fragmentation"},
            "sll_risk": "high",
            "sll_fix_guidance": {"strategy": "narrow_scope", "constraints": [], "notes": "reduce scope"},
            "verification": {"available": True, "test_command": "python -m pytest -q"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "SLL Fix Guidance:" in out
    assert "- strategy: narrow_scope" in out
    assert "- notes: reduce scope" in out
