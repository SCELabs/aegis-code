from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.create_plan import build_create_plan, format_create_plan


def test_create_plan_api_stack() -> None:
    plan = build_create_plan("build a REST API for users")
    assert plan["stack"]["name"] == "python-fastapi"
    assert plan["test_command"] == "python -m pytest -q"
    assert "fastapi" in plan["dependencies"]


def test_create_plan_cli_stack() -> None:
    plan = build_create_plan("terminal command parser")
    assert plan["stack"]["name"] == "python-cli"
    assert plan["test_command"] == "python -m pytest -q"


def test_create_plan_react_stack() -> None:
    plan = build_create_plan("react dashboard ui")
    assert plan["stack"]["name"] == "node-react"
    assert plan["test_command"] == "npm test"
    assert "vite" in plan["dependencies"]


def test_create_plan_fallback_stack() -> None:
    plan = build_create_plan("simple utility")
    assert plan["stack"]["name"] == "python-basic"
    assert plan["test_command"] == "python -m pytest -q"


def test_create_plan_formatter_includes_planning_note() -> None:
    plan = build_create_plan("build a CLI for logs")
    text = format_create_plan(plan)
    assert "Project plan:" in text
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
    assert "Planning only: no project files were created." in out
    assert not (tmp_path / "app" / "main.py").exists()
