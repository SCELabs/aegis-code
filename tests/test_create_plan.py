from __future__ import annotations

from pathlib import Path
import json

from aegis_code import cli
from aegis_code.create_scaffold import create_scaffold, load_external_profile, load_profile
from aegis_code.create_plan import build_create_plan, format_create_plan
from aegis_code.models import CommandResult
from aegis_code.scaffolds import available_stack_ids


def test_create_plan_api_stack() -> None:
    plan = build_create_plan("build a REST API for users")
    assert plan["stack"]["name"] == "python-fastapi"
    assert plan["test_command"] == "python -m pytest -q"
    assert "fastapi" in plan["dependencies"]


def test_create_plan_cli_stack() -> None:
    plan = build_create_plan("terminal command parser")
    assert plan["stack"]["name"] == "python-cli"
    assert plan["test_command"] == "python -m pytest -q"


def test_create_plan_cli_notes_stack() -> None:
    plan = build_create_plan("build a small CLI for notes")
    assert plan["stack"]["name"] == "python-cli"


def test_create_plan_terminal_tool_stack() -> None:
    plan = build_create_plan("terminal notes tool")
    assert plan["stack"]["name"] == "python-cli"


def test_create_plan_react_stack() -> None:
    plan = build_create_plan("react dashboard ui")
    assert plan["stack"]["name"] == "node-react"
    assert plan["test_command"] == "npm test"
    assert "vite" in plan["dependencies"]


def test_create_plan_react_dashboard_stack() -> None:
    plan = build_create_plan("react notes dashboard")
    assert plan["stack"]["name"] == "node-react"


def test_create_plan_rest_api_notes_stack() -> None:
    plan = build_create_plan("build a REST API for notes")
    assert plan["stack"]["name"] == "python-fastapi"


def test_create_plan_fallback_stack() -> None:
    plan = build_create_plan("simple utility")
    assert plan["stack"]["name"] == "python-basic"
    assert plan["test_command"] == "python -m pytest -q"


def test_create_plan_formatter_includes_planning_note() -> None:
    plan = build_create_plan("build a CLI for logs")
    text = format_create_plan(plan)
    assert "Project plan:" in text
    assert "Version: 0.1" in text
    assert "Planning only: no project files were created." in text


def test_cli_create_prints_plan_and_does_not_call_runtime(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no tests")))
    exit_code = cli.main(["create", "build a REST API"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Project plan:" in out
    assert "python-fastapi" in out
    assert "Version: 0.1" in out
    assert "Planning only: no project files were created." in out
    assert not (tmp_path / "app" / "main.py").exists()


def test_cli_create_with_target_without_confirm_writes_nothing(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "my-project"
    exit_code = cli.main(["create", "build a REST API", "--target", str(target)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Scaffold preview only" in out
    assert "Applied: false" in out
    assert not target.exists()


def test_cli_create_with_target_confirm_writes_scaffold(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "my-project"
    exit_code = cli.main(["create", "terminal command parser", "--target", str(target), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Scaffold created." in out
    assert "Applied: true" in out
    assert (target / ".aegis" / "aegis-code.yml").exists()
    assert (target / ".aegis" / "project_model.md").exists()
    assert (target / ".aegis" / "create_manifest.yml").exists()
    assert (target / "src" / "main.py").exists()
    assert (target / "tests" / "test_cli.py").exists()
    manifest = (target / ".aegis" / "create_manifest.yml").read_text(encoding="utf-8")
    assert "stack: python-cli" in manifest
    assert "stack_version: \"0.1\"" in manifest
    assert "scaffold_source: internal" in manifest
    assert "created_files:" in manifest
    assert "  - .aegis/create_manifest.yml" in manifest


def test_cli_create_refuses_non_empty_target(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "my-project"
    target.mkdir(parents=True, exist_ok=True)
    (target / "existing.txt").write_text("x", encoding="utf-8")
    exit_code = cli.main(["create", "simple utility", "--target", str(target), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "target exists and is not empty" in out


def test_cli_create_refuses_target_equal_cwd(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["create", "simple utility", "--target", str(tmp_path), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "target must not be the current repository root" in out


def test_create_plan_stack_override() -> None:
    plan = build_create_plan("inventory tracker", stack_id="python-fastapi")
    assert plan["stack"]["name"] == "python-fastapi"
    assert plan["stack"]["version"] == "0.1"


def test_cli_create_unknown_stack_lists_available(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["create", "inventory tracker", "--stack", "missing-stack"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Unknown stack 'missing-stack'" in out
    for stack_id in available_stack_ids():
        assert stack_id in out


def test_cli_create_list_stacks_no_side_effects(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.build_create_plan", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no plan")))
    monkeypatch.setattr("aegis_code.cli.create_scaffold", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no scaffold")))
    exit_code = cli.main(["create", "--list-stacks"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Available stacks:" in out
    for stack_id in available_stack_ids():
        assert stack_id in out
    assert "@0.1" in out
    assert not (tmp_path / ".aegis").exists()


def test_scaffold_profile_loads_correctly() -> None:
    profile = load_profile("python-cli")
    assert profile.get("name") == "python-cli"
    files = profile.get("files", [])
    assert isinstance(files, list)
    assert any(isinstance(item, dict) and item.get("path") == "src/main.py" for item in files)


def test_scaffold_missing_profile_handled() -> None:
    try:
        load_profile("missing-profile")
    except ValueError as exc:
        assert "Missing scaffold profile" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing profile")


def test_cli_create_list_profiles_no_side_effects(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.build_create_plan", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no plan")))
    monkeypatch.setattr("aegis_code.cli.create_scaffold", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no scaffold")))
    exit_code = cli.main(["create", "--list"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Available scaffolds:" in out
    assert "- python-cli" in out
    assert "- fastapi" in out
    assert "- node-react" in out
    assert not (tmp_path / ".aegis").exists()


def test_scaffold_files_created_from_profile(tmp_path: Path) -> None:
    target = tmp_path / "profile-proj"
    result = create_scaffold(
        target=target,
        cwd=tmp_path,
        stack_id="python-cli",
        stack_version="0.1",
        idea="terminal command parser",
        test_command="python -m pytest -q",
        confirm=True,
    )
    assert result.get("ok") is True
    assert (target / "src" / "main.py").exists()
    content = (target / "src" / "main.py").read_text(encoding="utf-8")
    assert "hello from cli" in content


def test_load_external_profile_success(tmp_path: Path) -> None:
    profile_path = tmp_path / "my-profile.yml"
    profile_path.write_text(
        "name: my-profile\n"
        "files:\n"
        "  - path: README.md\n"
        "    content: \"# Hello\\n\"\n",
        encoding="utf-8",
    )
    profile = load_external_profile(profile_path)
    assert profile["name"] == "my-profile"
    assert profile["files"][0]["path"] == "README.md"


def test_load_external_profile_missing_required_fields(tmp_path: Path) -> None:
    profile_path = tmp_path / "bad-profile.yml"
    profile_path.write_text("files: []\n", encoding="utf-8")
    try:
        load_external_profile(profile_path)
    except ValueError as exc:
        assert "missing required field: name" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing required fields")


def test_cli_create_from_preview_only(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    profile_path = tmp_path / "my-profile.yml"
    profile_path.write_text(
        "name: my-profile\n"
        "files:\n"
        "  - path: README.md\n"
        "    content: \"# Hello\\n\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_: (_ for _ in ()).throw(AssertionError("no commands")))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no commands")))
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no commands")))
    exit_code = cli.main(["create", "--from", str(profile_path)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Scaffold preview only" in out
    assert "Applied: false" in out
    assert not (tmp_path / "my-profile").exists()


def test_cli_create_from_confirm_writes_files(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    profile_path = tmp_path / "my-profile.yml"
    profile_path.write_text(
        "name: my-profile\n"
        "files:\n"
        "  - path: README.md\n"
        "    content: \"# Hello\\n\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_: (_ for _ in ()).throw(AssertionError("no commands")))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no commands")))
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no commands")))
    exit_code = cli.main(["create", "--from", str(profile_path), "--target", str(tmp_path / "new-app"), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Scaffold created." in out
    assert "Applied: true" in out
    assert (tmp_path / "new-app" / "README.md").exists()


def test_scaffold_rejects_parent_traversal_path(tmp_path: Path) -> None:
    target = tmp_path / "new-app"
    result = create_scaffold(
        target=target,
        cwd=tmp_path,
        stack_id="external:bad",
        stack_version="external",
        idea="bad",
        test_command="",
        confirm=True,
        profile_override={"name": "bad", "files": [{"path": "../evil.py", "content": "x"}]},
    )
    assert result.get("ok") is False
    assert result.get("code") == 2
    assert "unsafe file path" in str(result.get("message", ""))


def test_scaffold_rejects_unix_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "new-app"
    result = create_scaffold(
        target=target,
        cwd=tmp_path,
        stack_id="external:bad",
        stack_version="external",
        idea="bad",
        test_command="",
        confirm=True,
        profile_override={"name": "bad", "files": [{"path": "/root/file.py", "content": "x"}]},
    )
    assert result.get("ok") is False
    assert result.get("code") == 2
    assert "unsafe file path" in str(result.get("message", ""))


def test_scaffold_rejects_windows_absolute_path(tmp_path: Path) -> None:
    target = tmp_path / "new-app"
    result = create_scaffold(
        target=target,
        cwd=tmp_path,
        stack_id="external:bad",
        stack_version="external",
        idea="bad",
        test_command="",
        confirm=True,
        profile_override={"name": "bad", "files": [{"path": "C:\\something\\file.py", "content": "x"}]},
    )
    assert result.get("ok") is False
    assert result.get("code") == 2
    assert "unsafe file path" in str(result.get("message", ""))


def test_cli_create_validate_requires_confirm(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no validation")))
    exit_code = cli.main(["create", "inventory tracker", "--target", str(tmp_path / "proj"), "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "Validation requires --confirm (scaffold must exist)." in out


def test_cli_create_confirm_validate_success(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"

    def _ok_result(*_a, **_k) -> CommandResult:
        return CommandResult(name="test", command="python -m pytest -q", status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _ok_result)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no stabilization")))
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Validation: tests passed." in out


def test_cli_create_confirm_validate_failure_runs_aegis(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    called: dict[str, object] = {
        "cwd": None,
        "context": None,
        "mode": None,
        "budget_state": None,
        "runtime_policy": None,
    }

    def _fail_result(*_a, **_k) -> CommandResult:
        return CommandResult(name="test", command="python -m pytest -q", status="error", exit_code=1)

    def _record_run_task(*, options, cwd):
        called["cwd"] = cwd
        called["context"] = options.project_context
        called["mode"] = options.mode
        called["budget_state"] = options.budget_state
        called["runtime_policy"] = options.runtime_policy
        return {"status": "completed_tests_failed"}

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fail_result)
    monkeypatch.setattr("aegis_code.cli.run_task", _record_run_task)
    monkeypatch.setattr("aegis_code.cli.select_runtime_mode", lambda *_a, **_k: "cheapest")
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Validation: tests failed. Running Aegis stabilization..." in out
    assert "Report JSON: .aegis/runs/latest.json" in out
    assert "Report MD: .aegis/runs/latest.md" in out
    assert called["cwd"] == target
    assert isinstance(called["context"], dict)
    assert called["mode"] == "cheapest"
    assert isinstance(called["budget_state"], dict)
    assert isinstance(called["runtime_policy"], dict)


def test_create_installs_python_dependencies(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    calls: list[str] = []
    original_create_scaffold = cli.create_scaffold

    def _fake_create_scaffold(**kwargs):
        out = original_create_scaffold(**kwargs)
        (target / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        return out

    def _fake_shell(*, name, command, cwd=None, timeout_seconds=120):
        _ = (name, cwd, timeout_seconds)
        calls.append(command)
        return CommandResult(name="install_deps", command=command, status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.create_scaffold", _fake_create_scaffold)
    monkeypatch.setattr("aegis_code.cli.run_shell_command", _fake_shell)
    exit_code = cli.main(["create", "simple utility", "--target", str(target), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Dependencies install: ok (pip install -r requirements.txt)" in out
    assert "Dependencies: installed" in out
    assert "pip install -r requirements.txt" in calls


def test_create_installs_node_dependencies(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    calls: list[str] = []
    original_create_scaffold = cli.create_scaffold

    def _fake_create_scaffold(**kwargs):
        out = original_create_scaffold(**kwargs)
        (target / "package.json").write_text(
            '{"name":"x","packageManager":"pnpm@9.0.0","scripts":{"test":"vitest"}}',
            encoding="utf-8",
        )
        return out

    def _fake_shell(*, name, command, cwd=None, timeout_seconds=120):
        _ = (name, cwd, timeout_seconds)
        calls.append(command)
        return CommandResult(name="install_deps", command=command, status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.create_scaffold", _fake_create_scaffold)
    monkeypatch.setattr("aegis_code.cli.run_shell_command", _fake_shell)
    exit_code = cli.main(["create", "react dashboard ui", "--target", str(target), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Dependencies install: ok (pnpm install)" in out
    assert "pnpm install" in calls


def test_create_validate_runs_tests(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    called = {"tests": 0}

    def _fake_tests(*_a, **_k) -> CommandResult:
        called["tests"] += 1
        return CommandResult(name="test", command="python -m pytest -q", status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert called["tests"] == 1
    assert "Validation: tests passed." in out
    assert "Tests: passed" in out


def test_create_skips_provider_when_tests_pass(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"

    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: CommandResult(name="test", command="python -m pytest -q", status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("provider should be skipped")))
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Validation: tests passed." in out
    assert "Stabilization: not needed" in out


def test_create_handles_install_failure_gracefully(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    original_create_scaffold = cli.create_scaffold

    def _fake_create_scaffold(**kwargs):
        out = original_create_scaffold(**kwargs)
        (target / "requirements.txt").write_text("pytest\n", encoding="utf-8")
        return out

    def _fake_shell(**_k):
        return CommandResult(
            name="install_deps",
            command="pip install -r requirements.txt",
            status="failed",
            exit_code=1,
            output_preview="install failed",
            full_output="install failed",
        )

    monkeypatch.setattr("aegis_code.cli.create_scaffold", _fake_create_scaffold)
    monkeypatch.setattr("aegis_code.cli.run_shell_command", _fake_shell)
    exit_code = cli.main(["create", "simple utility", "--target", str(target), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Dependencies install: failed (pip install -r requirements.txt)" in out
    assert "install failed" in out
    assert "Dependencies: failed" in out


def test_create_validate_uses_probe_selected_command(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    called: dict[str, object] = {"command": None}

    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr(
        "aegis_code.cli.run_project_probe",
        lambda **_k: {
            "version": 1,
            "selected_test_command": "pytest -q",
            "verification": {"available": True, "confidence": "high", "reason": "observed", "environment_issue": False},
        },
    )

    def _record_tests(command: str, cwd=None) -> CommandResult:
        called["command"] = command
        return CommandResult(name="test", command=command, status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _record_tests)
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert called["command"] == "pytest -q"
    assert "Validation: tests passed." in out


def test_create_environment_missing_runtime_skips_stabilization(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"

    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr(
        "aegis_code.cli.run_project_probe",
        lambda **_k: {
            "version": 1,
            "selected_test_command": None,
            "verification": {
                "available": False,
                "confidence": "low",
                "reason": "runtime_missing_for_candidates",
                "environment_issue": True,
            },
        },
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no stabilization")))
    exit_code = cli.main(["create", "inventory tracker", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "runtime missing for verification command candidates" in out.lower()
    assert "Stabilization: skipped" in out


def test_create_node_missing_runtime_does_not_run_pytest_or_stabilize(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"

    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr(
        "aegis_code.cli.run_project_probe",
        lambda **_k: {
            "version": 1,
            "selected_test_command": None,
            "verification": {
                "available": False,
                "confidence": "low",
                "reason": "runtime_missing_for_candidates",
                "environment_issue": True,
            },
        },
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no pytest run")))
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no stabilization")))
    exit_code = cli.main(["create", "react dashboard ui", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "runtime missing for verification command candidates" in out.lower()
    assert "Stabilization: skipped" in out


def test_create_validate_skips_stabilization_when_no_supported_verification(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "proj"
    monkeypatch.setattr("aegis_code.cli.run_shell_command", lambda **_k: CommandResult(name="install", command="", status="ok", exit_code=0))
    monkeypatch.setattr(
        "aegis_code.cli.run_project_probe",
        lambda **_k: {
            "version": 1,
            "selected_test_command": None,
            "verification": {
                "available": False,
                "confidence": "low",
                "reason": "no test command candidates detected",
                "environment_issue": False,
            },
        },
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no tests run")))
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no stabilization")))
    exit_code = cli.main(["create", "simple utility", "--target", str(target), "--confirm", "--validate"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Validation: no verification command detected." in out
    assert "Stabilization: skipped" in out
