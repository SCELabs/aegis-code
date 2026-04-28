from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.budget import load_budget
from aegis_code.models import AegisDecision


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
        }

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["x", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Runtime Control:" in out
