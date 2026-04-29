from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli


def test_workspace_init_creates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "init"])
    assert exit_code == 0
    workspace_path = tmp_path / ".aegis" / "workspace.json"
    assert workspace_path.exists()
    data = json.loads(workspace_path.read_text(encoding="utf-8"))
    assert data["version"] == "0.1"
    assert data["projects"] == []


def test_workspace_init_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace_path = tmp_path / ".aegis" / "workspace.json"
    assert cli.main(["workspace", "init"]) == 0
    workspace_path.write_text('{"version":"0.1","projects":[{"path":"/x","name":"x"}]}', encoding="utf-8")
    assert cli.main(["workspace", "init"]) == 0
    data = json.loads(workspace_path.read_text(encoding="utf-8"))
    assert len(data["projects"]) == 1
    assert data["projects"][0]["name"] == "x"


def test_workspace_add_valid_directory_stores_absolute_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    exit_code = cli.main(["workspace", "add", str(project)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Added: {project.resolve()}" in out
    data = json.loads((tmp_path / ".aegis" / "workspace.json").read_text(encoding="utf-8"))
    assert len(data["projects"]) == 1
    assert data["projects"][0]["name"] == "project-a"
    assert data["projects"][0]["path"] == str(project.resolve())


def test_workspace_duplicate_prevented(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "add", str(project)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Error: already exists" in out


def test_workspace_add_rejects_non_existent_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    missing = tmp_path / "does-not-exist"
    assert cli.main(["workspace", "init"]) == 0
    exit_code = cli.main(["workspace", "add", str(missing)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Error: path does not exist" in out


def test_workspace_status_missing_returns_exit_1(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "status"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_status_shows_projects_and_missing_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir(parents=True, exist_ok=True)
    project_b.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project_a)]) == 0
    assert cli.main(["workspace", "add", str(project_b)]) == 0
    project_b.rmdir()
    exit_code = cli.main(["workspace", "status"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace:" in out
    assert "- Projects: 2" in out
    assert "project-a" in out
    assert "project-b" in out
    assert "exists: true" in out
    assert "exists: false" in out


def test_workspace_remove_success(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "remove", str(project)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert f"Removed: {project.resolve()}" in out
    status_code = cli.main(["workspace", "status"])
    status_out = capsys.readouterr().out
    assert status_code == 0
    assert "- Projects: 0" in status_out


def test_workspace_remove_not_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    missing = tmp_path / "missing-project"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "remove", str(missing)])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: project not found" in out
    data = json.loads((tmp_path / ".aegis" / "workspace.json").read_text(encoding="utf-8"))
    assert len(data["projects"]) == 1


def test_workspace_remove_updates_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir(parents=True, exist_ok=True)
    project_b.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project_a)]) == 0
    assert cli.main(["workspace", "add", str(project_b)]) == 0
    assert cli.main(["workspace", "remove", str(project_a)]) == 0
    data = json.loads((tmp_path / ".aegis" / "workspace.json").read_text(encoding="utf-8"))
    assert len(data["projects"]) == 1
    assert data["projects"][0]["name"] == "project-b"


def test_workspace_remove_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    exit_code = cli.main(["workspace", "remove", str(project)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_status_detailed_basic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "status", "--detailed"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "project-a" in out
    assert "exists: true" in out
    assert "config: missing" in out
    assert "budget: not set" in out
    assert "context: missing" in out
    assert "latest run: missing" in out
    assert "mode: unknown" in out


def test_workspace_status_detailed_missing_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    project.rmdir()
    exit_code = cli.main(["workspace", "status", "--detailed"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "project-a" in out
    assert "exists: false" in out


def test_workspace_status_detailed_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "status", "--detailed"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_status_detailed_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "context").mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "runs").mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (project / ".aegis" / "budget.json").write_text("{}", encoding="utf-8")
    (project / ".aegis" / "runs" / "latest.json").write_text("{}", encoding="utf-8")
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "status", "--detailed"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "config: found" in out
    assert "budget: set" in out
    assert "context: available" in out
    assert "latest run: found" in out
    assert "mode: balanced" in out


def test_workspace_overview_basic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace Overview:" in out
    assert "- Projects: 1" in out
    assert "- Available: 1" in out
    assert "- Missing: 0" in out


def test_workspace_overview_mixed(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir(parents=True, exist_ok=True)
    project_b.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project_a)]) == 0
    assert cli.main(["workspace", "add", str(project_b)]) == 0
    project_b.rmdir()
    exit_code = cli.main(["workspace", "overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Projects: 2" in out
    assert "- Available: 1" in out
    assert "- Missing: 1" in out


def test_workspace_overview_flags(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "context").mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "runs").mkdir(parents=True, exist_ok=True)
    (project / ".aegis" / "aegis-code.yml").write_text("mode: balanced\n", encoding="utf-8")
    (project / ".aegis" / "budget.json").write_text("{}", encoding="utf-8")
    (project / ".aegis" / "runs" / "latest.json").write_text("{}", encoding="utf-8")
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "overview"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Configured: 1" in out
    assert "- Budgets set: 1" in out
    assert "- Context ready: 1" in out
    assert "- Latest runs: 1" in out


def test_workspace_overview_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "overview"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_refresh_context_basic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "refresh-context"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace context refresh:" in out
    assert "- Projects: 1" in out
    assert "- Refreshed: 1" in out
    assert "- Skipped (missing): 0" in out


def test_workspace_refresh_context_missing_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    project.rmdir()
    exit_code = cli.main(["workspace", "refresh-context"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Projects: 1" in out
    assert "- Refreshed: 0" in out
    assert "- Skipped (missing): 1" in out


def test_workspace_refresh_context_multiple(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir(parents=True, exist_ok=True)
    project_b.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project_a)]) == 0
    assert cli.main(["workspace", "add", str(project_b)]) == 0
    exit_code = cli.main(["workspace", "refresh-context"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Projects: 2" in out
    assert "- Refreshed: 2" in out
    assert "- Skipped (missing): 0" in out


def test_workspace_refresh_context_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "refresh-context"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_run_preview_basic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "run", "plan release", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace run preview:" in out
    assert "- Task: plan release" in out
    assert "- Projects: 1" in out
    assert "- Skipped (missing): 0" in out
    assert "action: would_run" in out


def test_workspace_run_preview_missing_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    project.rmdir()
    exit_code = cli.main(["workspace", "run", "plan release", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Projects: 0" in out
    assert "- Skipped (missing): 1" in out


def test_workspace_run_preview_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "run", "plan release", "--dry-run"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_run_requires_dry_run(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "run", "plan release"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: must specify either --dry-run or --confirm" in out


def test_workspace_run_confirm_basic(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0

    def _fake_run_task(**_: object) -> dict:
        return {"status": "ok"}

    monkeypatch.setattr("aegis_code.workspace.run_task", _fake_run_task)
    exit_code = cli.main(["workspace", "run", "plan release", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Workspace run:" in out
    assert "- Executed: 1" in out
    assert "- Skipped (missing): 0" in out
    assert "- Skipped (budget): 0" in out


def test_workspace_run_confirm_missing_project(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    project.rmdir()

    def _fake_run_task(**_: object) -> dict:
        return {"status": "ok"}

    monkeypatch.setattr("aegis_code.workspace.run_task", _fake_run_task)
    exit_code = cli.main(["workspace", "run", "plan release", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Executed: 0" in out
    assert "- Skipped (missing): 1" in out


def test_workspace_run_confirm_budget_block(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    monkeypatch.setattr("aegis_code.workspace._allow_runtime_for_workspace", lambda *_args, **_kwargs: False)

    def _fake_run_task(**_: object) -> dict:
        raise AssertionError("run_task should not be called when budget blocks")

    monkeypatch.setattr("aegis_code.workspace.run_task", _fake_run_task)
    exit_code = cli.main(["workspace", "run", "plan release", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "- Executed: 0" in out
    assert "- Skipped (budget): 1" in out


def test_workspace_run_confirm_no_workspace(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["workspace", "run", "plan release", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No workspace found. Run `aegis-code workspace init`." in out


def test_workspace_run_requires_flag(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project-a"
    project.mkdir(parents=True, exist_ok=True)
    assert cli.main(["workspace", "init"]) == 0
    assert cli.main(["workspace", "add", str(project)]) == 0
    exit_code = cli.main(["workspace", "run", "plan release"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Error: must specify either --dry-run or --confirm" in out
