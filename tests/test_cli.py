from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.batch_executor import BatchExecutionResult
from aegis_code.patches.apply_check import check_patch_text
from tests.helpers import command_result_from_output
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


def test_setup_help_marks_preferred_onboarding_flow() -> None:
    out = cli._build_setup_parser().format_help()
    assert "Preferred onboarding and initialization command." in out
    assert "aegis-code setup" in out
    assert "aegis-code config provider" in out
    assert "aegis-code patch" in out
    assert "Compatibility commands remain available" in out
    assert "aegis-code init" in out
    assert "onboard" in out
    assert "aegis-code doctor" in out


def test_init_help_marks_compatibility_direct_command() -> None:
    out = cli._build_init_parser().format_help()
    assert "Compatibility/direct project initialization command." in out
    assert "Preferred onboarding" in out
    assert "`aegis-code setup`" in out


def test_onboard_help_marks_compatibility_direct_command() -> None:
    out = cli._build_onboard_parser().format_help()
    assert "Compatibility/direct Aegis API key onboarding command." in out
    assert "Preferred onboarding" in out
    assert "`aegis-code setup`" in out


def test_init_command_still_routes_to_existing_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_handle_init(argv: list[str]) -> int:
        captured["argv"] = list(argv)
        return 0

    monkeypatch.setattr("aegis_code.cli.handle_init", _fake_handle_init)
    assert cli.main(["init", "--force"]) == 0
    assert captured["argv"] == ["--force"]


def test_onboard_command_still_routes_to_existing_onboarding(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def _fake_run_onboard(email: str, cwd: Path) -> dict[str, object]:
        captured["email"] = email
        captured["cwd"] = cwd
        return {"success": True}

    monkeypatch.setattr("aegis_code.cli.run_onboard", _fake_run_onboard)
    exit_code = cli.main(["onboard", "--email", "user@example.com"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert captured["email"] == "user@example.com"
    assert "Aegis onboarding complete." in out


def test_docs_mark_setup_preferred_and_init_onboard_compatible() -> None:
    root = Path(__file__).resolve().parents[1]
    command_docs = (root / "docs" / "commands.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "Preferred public onboarding flow:" in command_docs
    assert "`aegis-code setup`" in command_docs
    assert "`aegis-code config provider ...`" in command_docs
    assert "`aegis-code patch ...`" in command_docs
    assert "Compatibility commands remain available:" in command_docs
    assert "`aegis-code init`" in command_docs
    assert "`aegis-code onboard`" in command_docs

    assert "Preferred onboarding and initialization:" in readme
    assert "aegis-code setup" in readme


def test_inspection_command_help_roles_are_concise_and_non_overlapping() -> None:
    status_help = cli._build_status_parser().format_help()
    report_help = cli._build_report_parser().format_help()
    doctor_help = cli._build_doctor_parser().format_help()
    overview_help = cli._build_overview_parser().format_help()
    probe_help = cli._build_probe_parser().format_help()
    next_help = cli._build_next_parser().format_help()
    usage_help = cli._build_usage_parser().format_help()

    assert "Current project state and latest run summary." in status_help
    assert "Detailed view of the latest run report." in report_help
    assert "Environment and setup diagnostics." in doctor_help
    assert "setup --check" in doctor_help
    assert "High-level project summary." in overview_help
    assert "Stack detection and verification capability discovery." in probe_help
    assert "Recommended next actions." in next_help
    assert "Aegis API usage summary." in usage_help


def test_docs_define_inspection_and_diagnostics_toolkit() -> None:
    root = Path(__file__).resolve().parents[1]
    command_docs = (root / "docs" / "commands.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    for content in (command_docs, readme):
        assert "Inspection & Diagnostics Commands" in content
        assert "aegis-code status" in content
        assert "aegis-code report" in content
        assert "aegis-code doctor" in content
        assert "aegis-code overview" in content
        assert "aegis-code probe" in content
        assert "aegis-code next" in content
        assert "aegis-code usage" in content
        assert "Run `aegis-code status` first" in content


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


def test_task_prints_aegis_guidance_when_available(tmp_path: Path, monkeypatch, capsys) -> None:
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
            "aegis_guidance": {
                "available": True,
                "actions": ["narrow scope"],
                "explanation": "Try a smaller patch.",
                "used_fallback": False,
            },
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Aegis Guidance:" in out
    assert "Try a smaller patch." in out


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


def test_patch_command_builds_explicit_scope_contract(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("x = 1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["scope"] = getattr(options, "scope_contract", None)
        captured["command"] = getattr(options, "command", None)
        return {
            "task": "implement todo CLI commands",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "x"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(["patch", "--file", "src/main.py", "implement todo CLI commands"])
    _ = capsys.readouterr()
    assert exit_code == 1
    assert captured["command"] == "patch"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_targets"] == ["src/main.py"]
    assert scope["allow_new_files"] is False
    assert scope["allowed_operations"] == ["replace"]


def test_patch_command_allows_missing_targets_when_allow_create(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "create config loader",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": True, "status": "generated", "path": ".aegis/runs/latest.diff"},
            "structured_patch": {"status": "accepted"},
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
    exit_code = cli.main(["patch", "--file", "src/config.py", "--allow-create", "create config loader"])
    _ = capsys.readouterr()
    assert exit_code == 0
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allow_new_files"] is True
    assert "create" in scope["allowed_operations"]


def test_patch_command_append_threads_operation_into_scope_and_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["scope"] = getattr(options, "scope_contract", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["command"] = getattr(options, "command", None)
        return {
            "task": "add tests for todo CLI",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": True, "status": "generated", "path": ".aegis/runs/latest.diff"},
            "patch_operation": {"operation": "append"},
            "structured_patch": {"status": "accepted"},
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
    exit_code = cli.main(["patch", "--file", "tests/test_cli.py", "--operation", "append", "add tests for todo CLI"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch operation: append" in out
    assert captured["command"] == "patch"
    assert captured["operation"] == "append"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["append"]
    assert scope["allow_new_files"] is False


def test_patch_parser_path_sets_command_and_operation_for_explicit_append(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        return {
            "task": "add tests for todo CLI",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "append_output_invalid"},
            "patch_operation": {"operation": "append"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(["patch", "--file", "tests/test_cli.py", "--operation", "append", "add tests for todo CLI"])
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "append"


def test_patch_parser_accepts_create_file_operation_and_threads_command(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "create helper functions for notes",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_target_exists"},
            "patch_operation": {"operation": "create-file"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "create-file",
            "create helper functions for notes",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "create-file"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allow_new_files"] is True


def test_patch_parser_accepts_insert_after_and_threads_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n// ANCHOR\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "insert helper",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_anchor_not_found"},
            "patch_operation": {"operation": "insert-after"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "insert-after",
            "--anchor",
            "ANCHOR",
            "insert helper",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "insert-after"
    assert captured["anchor"] == "ANCHOR"


def test_patch_parser_accepts_insert_before_and_threads_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n// ANCHOR\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "insert helper",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_anchor_not_found"},
            "patch_operation": {"operation": "insert-before"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "insert-before",
            "--anchor",
            "ANCHOR",
            "insert helper",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "insert-before"
    assert captured["anchor"] == "ANCHOR"


def test_patch_parser_accepts_replace_block_and_threads_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "replace block",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_anchor_not_found"},
            "patch_operation": {"operation": "replace-block"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "replace-block",
            "--anchor",
            "OLD BLOCK",
            "replace block",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "replace-block"
    assert captured["anchor"] == "OLD BLOCK"


def test_patch_parser_accepts_delete_block_and_threads_anchor(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("line 1\nOLD BLOCK\nline 3\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "delete block",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_anchor_not_found"},
            "patch_operation": {"operation": "delete-block"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "delete-block",
            "--anchor",
            "OLD BLOCK",
            "delete block",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "delete-block"
    assert captured["anchor"] == "OLD BLOCK"


def test_patch_parser_accepts_replace_file_operation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export const x = 1;\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "rewrite module",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "replace-file"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "replace-file",
            "rewrite module",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "replace-file"
    assert captured["anchor"] is None


def test_patch_parser_accepts_delete_file_operation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "old-notes.md").write_text("obsolete\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["anchor"] = getattr(options, "anchor", None)
        return {
            "task": "delete obsolete file",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "delete-file"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "docs/old-notes.md",
            "--operation",
            "delete-file",
            "delete obsolete file",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "delete-file"
    assert captured["anchor"] is None


def test_patch_parser_accepts_rename_file_and_threads_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "old_name.py").write_text("x = 1\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["destination"] = getattr(options, "destination_path", None)
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "rename file",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "rename-file"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/old_name.py",
            "--operation",
            "rename-file",
            "--target",
            "src/new_name.py",
            "Rename this file.",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "rename-file"
    assert captured["destination"] == "src/new_name.py"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["rename-file"]
    assert scope["destination_path"] == "src/new_name.py"


def test_patch_rename_file_requires_target(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "old_name.py").write_text("x = 1\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/old_name.py",
            "--operation",
            "rename-file",
            "Rename this file.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation rename-file requires --target destination path" in out


def test_patch_rename_file_requires_single_source_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/a.py",
            "--file",
            "src/b.py",
            "--operation",
            "rename-file",
            "--target",
            "src/new_name.py",
            "Rename this file.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation rename-file requires exactly one --file source path" in out


def test_patch_parser_accepts_move_file_and_threads_target(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "utils.js").write_text("export const value = 1;\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["destination"] = getattr(options, "destination_path", None)
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "move file",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "move-file"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/utils.js",
            "--operation",
            "move-file",
            "--target",
            "src/lib/utils.js",
            "Move this file.",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "move-file"
    assert captured["destination"] == "src/lib/utils.js"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["move-file"]
    assert scope["destination_path"] == "src/lib/utils.js"


def test_patch_move_file_requires_target(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "utils.js").write_text("export const value = 1;\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/utils.js",
            "--operation",
            "move-file",
            "Move this file.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation move-file requires --target destination path" in out


def test_patch_move_file_requires_single_source_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "a.js").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "b.js").write_text("export const b = 2;\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/a.js",
            "--file",
            "src/b.js",
            "--operation",
            "move-file",
            "--target",
            "src/lib/utils.js",
            "Move this file.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation move-file requires exactly one --file source path" in out


def test_patch_batch_requires_batch_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(
        [
            "patch",
            "--operation",
            "batch",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation batch requires --batch-file" in out


def test_patch_batch_file_only_valid_for_batch_operation(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "README.md",
            "--operation",
            "append",
            "--batch-file",
            ".aegis/batch.json",
            "append docs",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--batch-file is only valid when --operation batch is selected" in out


def test_patch_batch_invalid_file_blocks_cleanly(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    batch_path = tmp_path / ".aegis" / "batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text("{ invalid json", encoding="utf-8")
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("runtime should not run for batch validation")))
    exit_code = cli.main(
        [
            "patch",
            "--operation",
            "batch",
            "--batch-file",
            ".aegis/batch.json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "batch file is not valid JSON" in out


def test_patch_batch_valid_file_executes_and_writes_combined_diff(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    batch_path = tmp_path / ".aegis" / "batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": [
                    {
                        "operation": "create-file",
                        "target_file": "src/utils.js",
                        "task": "Create utility helpers.",
                    },
                    {
                        "operation": "replace-symbol",
                        "target_file": "src/main.js",
                        "symbol": "run",
                        "task": "Use helpers.",
                    },
                ],
                "options": {"stop_on_first_failure": True},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("runtime should not run for batch execution")))
    monkeypatch.setattr(
        "aegis_code.cli.execute_batch",
        lambda batch, cwd, runtime_context: BatchExecutionResult(
            success=True,
            diff_text=(
                "diff --git a/src/utils.js b/src/utils.js\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                "+++ b/src/utils.js\n"
                "@@ -0,0 +1 @@\n"
                "+export const helper = 1;\n"
            ),
            total_steps=2,
            completed_steps=2,
            step_results=[
                {
                    "index": 1,
                    "operation": "create-file",
                    "target_file": "src/utils.js",
                    "status": "generated",
                    "error": None,
                    "patch_generated": True,
                },
                {
                    "index": 2,
                    "operation": "replace-symbol",
                    "target_file": "src/main.js",
                    "status": "generated",
                    "error": None,
                    "patch_generated": True,
                    "symbol": "run",
                },
            ],
            failed_step_index=None,
            error=None,
        ),
    )
    exit_code = cli.main(
        [
            "patch",
            "--operation",
            "batch",
            "--batch-file",
            ".aegis/batch.json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch status: generated" in out
    assert "Patch operation: batch" in out
    assert "Batch completed successfully." in out
    assert "Steps completed: 2/2" in out
    latest_diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    assert latest_diff.exists()
    assert "diff --git a/src/utils.js b/src/utils.js" in latest_diff.read_text(encoding="utf-8")
    latest_json = tmp_path / ".aegis" / "runs" / "latest.json"
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload.get("patch_operation", {}).get("operation") == "batch"
    assert payload.get("control_guidance") is None
    assert payload.get("advisory_guidance") is None
    assert payload.get("aegis_guidance") is None
    batch_report = payload.get("batch_report", {})
    assert batch_report.get("success") is True
    assert batch_report.get("total_steps") == 2
    assert batch_report.get("completed_steps") == 2
    assert batch_report.get("failed_step_index") is None
    assert len(batch_report.get("steps", [])) == 2


def test_patch_batch_failure_outputs_step_summary_and_writes_batch_report(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    batch_path = tmp_path / ".aegis" / "batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(
        json.dumps(
            {
                "version": 1,
                "operations": [
                    {
                        "operation": "create-file",
                        "target_file": "src/utils.js",
                        "task": "Create utility helpers.",
                    },
                    {
                        "operation": "replace-symbol",
                        "target_file": "src/main.js",
                        "symbol": "run",
                        "task": "Use helpers.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("runtime should not run for batch execution")))
    monkeypatch.setattr(
        "aegis_code.cli.execute_batch",
        lambda batch, cwd, runtime_context: BatchExecutionResult(
            success=False,
            diff_text="",
            total_steps=2,
            completed_steps=1,
            step_results=[
                {
                    "index": 1,
                    "operation": "create-file",
                    "target_file": "src/utils.js",
                    "status": "generated",
                    "error": None,
                    "patch_generated": True,
                },
                {
                    "index": 2,
                    "operation": "replace-symbol",
                    "target_file": "src/main.js",
                    "status": "blocked",
                    "error": "operation_symbol_not_found",
                    "patch_generated": False,
                    "symbol": "run",
                },
            ],
            failed_step_index=2,
            error="operation_symbol_not_found",
        ),
    )
    exit_code = cli.main(
        [
            "patch",
            "--operation",
            "batch",
            "--batch-file",
            ".aegis/batch.json",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Patch status: blocked" in out
    assert "Patch operation: batch" in out
    assert "Batch failed at step 2/2:" in out
    assert "- operation: replace-symbol" in out
    assert "- target: src/main.js" in out
    assert "- status: blocked" in out
    assert "- error: operation_symbol_not_found" in out
    latest_json = tmp_path / ".aegis" / "runs" / "latest.json"
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload.get("status") == "batch_blocked"
    assert payload.get("control_guidance") is None
    assert payload.get("advisory_guidance") is None
    assert payload.get("aegis_guidance") is None
    batch_report = payload.get("batch_report", {})
    assert batch_report.get("success") is False
    assert batch_report.get("total_steps") == 2
    assert batch_report.get("completed_steps") == 1
    assert batch_report.get("failed_step_index") == 2
    assert len(batch_report.get("steps", [])) == 2


def test_patch_insert_after_requires_anchor(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "helpers.js").write_text("const a = 1;\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/helpers.js",
            "--operation",
            "insert-after",
            "Insert helper.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation insert-after requires --anchor" in out


def test_patch_delete_symbol_requires_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function removeMe() { return 1; }\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "delete-symbol",
            "Delete symbol.",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation delete-symbol requires --symbol" in out


def test_patch_parser_accepts_replace_symbol_and_threads_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(text) { return text; }\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["symbol"] = getattr(options, "symbol", None)
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "rewrite symbol",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "replace-symbol"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "replace-symbol",
            "--symbol",
            "addNote",
            "rewrite symbol",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "replace-symbol"
    assert captured["symbol"] == "addNote"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["replace-symbol"]
    assert scope["symbol"] == "addNote"


def test_patch_replace_symbol_requires_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(text) { return text; }\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "replace-symbol",
            "rewrite symbol",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation replace-symbol requires --symbol" in out


def test_patch_parser_accepts_delete_symbol_and_threads_symbol(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function removeMe() { return 1; }\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["command"] = getattr(options, "command", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        captured["symbol"] = getattr(options, "symbol", None)
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "task": "delete symbol",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "operation_validation_failed"},
            "patch_operation": {"operation": "delete-symbol"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "delete-symbol",
            "--symbol",
            "removeMe",
            "delete symbol",
        ]
    )
    assert exit_code == 1
    assert captured["command"] == "patch"
    assert captured["operation"] == "delete-symbol"
    assert captured["symbol"] == "removeMe"
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["delete-symbol"]
    assert scope["symbol"] == "removeMe"


def test_patch_delete_symbol_requires_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function removeMe() { return 1; }\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "src/notes.js",
            "--operation",
            "delete-symbol",
            "delete symbol",
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--operation delete-symbol requires --symbol" in out


def test_patch_command_does_not_auto_select_append_for_additive_single_existing_target(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote() {}\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["scope"] = getattr(options, "scope_contract", None)
        captured["operation"] = getattr(options, "patch_operation", None)
        return {
            "task": "add hasNotes(notes)",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": True, "status": "generated", "path": ".aegis/runs/latest.diff"},
            "patch_operation": {},
            "structured_patch": {"status": "accepted"},
            "patch_quality": None,
            "sll_analysis": {"available": False},
            "verification": {"available": True, "test_command": "npm test"},
            "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
            "budget_state": {"available": False, "remaining_estimate": None},
            "project_context": {"available": False},
            "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
            "selected_model_tier": "mid",
            "selected_model": "openai:gpt-4.1-mini",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["patch", "--file", "src/notes.js", "add hasNotes(notes)"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch operation: append" not in out
    assert captured["operation"] is None
    scope = captured["scope"]
    assert isinstance(scope, dict)
    assert scope["allowed_operations"] == ["replace"]
    assert "This task appears additive." in out
    assert "For safer patch generation consider:" in out
    assert "--operation append" in out


def test_patch_command_shows_additive_append_hint_without_operation(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["operation"] = getattr(options, "patch_operation", None)
        return {
            "task": "add tests for todo CLI",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "x"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(["patch", "--file", "tests/test_cli.py", "add tests for todo CLI"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert captured["operation"] is None
    assert "This task appears additive." in out
    assert "For safer patch generation consider:" in out
    assert "--operation append" in out


def test_patch_command_destructive_test_rewrite_shows_append_hint(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")

    def _fake_run_task(**kwargs: object):
        _ = kwargs["options"]
        return {
            "task": "add tests for add/list/complete todo CLI commands",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "destructive_test_rewrite"},
            "structured_patch": {"status": "failed"},
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
    exit_code = cli.main(["patch", "--file", "tests/test_cli.py", "add tests for add/list/complete todo CLI commands"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Patch error: destructive_test_rewrite" in out
    assert "Hint:" in out
    assert "Try append-only mode:" in out
    assert 'aegis-code patch --file tests/test_cli.py --operation append "add tests..."' in out


def test_patch_command_additive_tests_without_append_surfaces_destructive_test_rewrite(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")

    def _fake_run_task(**kwargs: object):
        _ = kwargs["options"]
        return {
            "task": "add tests for add/list/complete todo CLI commands",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "destructive_test_rewrite"},
            "structured_patch": {"status": "failed", "failure_reason": "invalid_json"},
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
    exit_code = cli.main(["patch", "--file", "tests/test_cli.py", "add tests for add/list/complete todo CLI commands"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Patch error: destructive_test_rewrite" in out


def test_patch_command_additive_docs_without_append_shows_stronger_guidance(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Title\n", encoding="utf-8")

    def _fake_run_task(**kwargs: object):
        _ = kwargs["options"]
        return {
            "task": "add README usage examples",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": True, "status": "generated", "error": None},
            "structured_patch": {"status": "accepted"},
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
    exit_code = cli.main(["patch", "--file", "README.md", "add README usage examples"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "This looks like an additive docs task." in out
    assert "For controlled additive edits, rerun with:" in out
    assert "--operation append" in out


def test_patch_command_destructive_docs_rewrite_shows_append_hint(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Title\n", encoding="utf-8")

    def _fake_run_task(**kwargs: object):
        _ = kwargs["options"]
        return {
            "task": "add README usage examples",
            "mode": "balanced",
            "dry_run": False,
            "status": "completed_tests_failed",
            "failures": {"failure_count": 1},
            "symptoms": [],
            "retry_policy": {"retry_attempted": False, "retry_count": 0},
            "patch_plan": {"proposed_changes": []},
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "destructive_docs_rewrite"},
            "structured_patch": {"status": "failed", "failure_reason": "destructive_docs_rewrite"},
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
    exit_code = cli.main(["patch", "--file", "README.md", "add README usage examples"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Patch error: destructive_docs_rewrite" in out
    assert "Try append-only mode:" in out
    assert 'aegis-code patch --file README.md --operation append "add README usage examples..."' in out


def test_fix_prefers_source_target_for_imported_failing_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "tests" / "test_calculator.py").write_text(
        "from src.calculator import add\n\ndef test_add():\n    assert add(1, 1) == 2\n",
        encoding="utf-8",
    )
    fail_output = "\n".join(
        [
            "=================================== FAILURES ===================================",
            "___________________________________ test_add ___________________________________",
            "",
            "    def test_add():",
            ">       assert add(1, 1) == 2",
            "E       assert 0 == 2",
            "",
            "tests/test_calculator.py:4: AssertionError",
            "FAILED tests/test_calculator.py::test_add - AssertionError: assert 0 == 2",
        ]
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(fail_output, status="failed", exit_code=1),
    )
    captured: dict[str, object] = {}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["task"] = getattr(options, "task", "")
        captured["scope"] = getattr(options, "scope_contract", None)
        return {
            "status": "completed_tests_failed",
            "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "x", "path": None},
            "apply_safety": "BLOCKED",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr()
    assert exit_code == 1
    task_text = str(captured.get("task", ""))
    assert "preferred source target: src/calculator.py" in task_text
    scope = captured.get("scope")
    assert isinstance(scope, dict)
    assert scope.get("allowed_targets", [])[0] == "src/calculator.py"
    assert "tests/test_calculator.py" in scope.get("allowed_targets", [])
    assert scope.get("source") == "cli_explicit"


def test_fix_blocks_test_weakening_detected(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis" / "runs").mkdir(parents=True, exist_ok=True)
    fail_output = "\n".join(
        [
            "=================================== FAILURES ===================================",
            "_______________________________ test_example_failure ___________________________",
            "",
            ">       assert expected == actual",
            "E       AssertionError:",
            "E       - expected",
            "E       + broken",
            "",
            "tests/test_example.py:12: AssertionError",
            "FAILED tests/test_example.py::test_example_failure - AssertionError",
        ]
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(fail_output, status="failed", exit_code=1),
    )
    weakening_diff = (
        "diff --git a/tests/test_example.py b/tests/test_example.py\n"
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-    assert result == \"expected\"\n"
        "+    assert result == \"broken\"\n"
    )
    diff_path = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff_path.write_text(weakening_diff, encoding="utf-8")

    def _fake_run_task(**_: object):
        return {
            "status": "completed_tests_failed",
            "patch_diff": {"attempted": True, "available": True, "status": "generated", "path": str(diff_path), "error": None},
            "apply_safety": "HIGH",
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "test_weakening_detected" in out


def test_fix_valid_source_repair_diff_passes_apply_check(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    diff_text = (
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n"
    )
    checked = check_patch_text(diff_text, cwd=tmp_path)
    assert checked["valid"] is True
    assert checked["apply_blocked"] is False


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


def test_report_command_falls_back_to_latest_json_when_md_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
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
        "patch_plan": {"strategy": "none", "confidence": 0.0, "proposed_changes": []},
        "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "append_output_invalid"},
        "patch_quality": None,
        "patch_operation": {"operation": "append", "source": "cli"},
        "patch_safety": {"highest_severity": "pass", "issues": []},
        "status": "completed_tests_failed",
        "notes": [],
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    exit_code = cli.main(["report"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Latest report source:" in out
    assert "## Patch Diagnosis" in out
    assert "Patch operation: `append`" in out


def test_report_and_cli_patch_failure_reason_match(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    payload = {
        "task": "add tests",
        "mode": "balanced",
        "dry_run": False,
        "status": "completed_tests_failed",
        "failures": {"failure_count": 1},
        "symptoms": [],
        "retry_policy": {"retry_attempted": False, "retry_count": 0},
        "patch_plan": {"proposed_changes": [{"file": "tests/test_cli.py"}], "allowed_targets": ["tests/test_cli.py"]},
        "patch_diff": {"attempted": True, "available": False, "status": "blocked", "error": "destructive_test_rewrite"},
        "structured_patch": {"status": "failed", "failure_reason": "invalid_json"},
        "patch_quality": None,
        "patch_safety": {"highest_severity": "pass", "issues": []},
        "verification": {"available": True, "test_command": "python -m pytest -q"},
        "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        "budget_state": {"available": False, "remaining_estimate": None},
        "project_context": {"available": False},
        "adapter": {"mode": "local", "aegis_client_available": False, "fallback_reason": "disabled"},
        "selected_model_tier": "mid",
        "selected_model": "openai:gpt-4.1-mini",
    }

    def _fake_run_task(**kwargs: object):
        _ = kwargs["options"]
        return payload

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    assert cli.main(["patch", "--file", "tests/test_cli.py", "add tests"]) == 1
    cli_out = capsys.readouterr().out
    assert "Patch error: destructive_test_rewrite" in cli_out
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    assert cli.main(["report"]) == 0
    report_out = capsys.readouterr().out
    assert "Patch error: `destructive_test_rewrite`" in report_out


def test_patch_cli_operation_source_persists_in_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_placeholder.py").write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")
    exit_code = cli.main(
        [
            "patch",
            "--file",
            "tests/test_placeholder.py",
            "--operation",
            "append",
            "add one small test case",
        ]
    )
    assert exit_code in {0, 1}
    report_md = (tmp_path / ".aegis" / "runs" / "latest.md").read_text(encoding="utf-8")
    assert "Patch operation: `append`" in report_md
    assert "Operation source: `cli`" in report_md
