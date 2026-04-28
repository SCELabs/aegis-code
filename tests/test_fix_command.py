from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.models import CommandResult


def _write_latest_json(tmp_path: Path, payload: dict) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_fix_tests_pass_no_action(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 0},
                "patch_diff": {"available": False, "path": None},
                "patch_quality": None,
            },
        )
        return {}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Fix summary:" in out
    assert "Verification command: pytest -q" in out
    assert "Failure count: 0" in out
    assert "Tests passed. No action required." in out
    assert "Next: run `aegis-code report` for details." in out


def test_fix_fail_diff_exists_no_confirm_no_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )

    def _fake_run_task(**_: object):
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 1},
                "patch_diff": {"available": True, "path": str(diff)},
                "patch_quality": {"confidence": 0.8},
            },
        )
        return {}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no apply")),
    )
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Fix summary:" in out
    assert "Failure count: 1" in out
    assert f"Patch diff path: {diff}" in out
    assert "Patch proposal:" in out
    assert "Quality: 0.8" in out
    assert f"Preview available. Use `aegis-code apply {diff}` to inspect." in out
    assert "Use `aegis-code fix --confirm` to apply this patch." in out


def test_fix_fail_diff_exists_confirm_applies_and_reruns_tests(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )
    called = {"apply": False, "tests": False}

    def _fake_run_task(**_: object):
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 1},
                "patch_diff": {"available": True, "path": str(diff)},
                "patch_quality": {"confidence": 0.9},
            },
        )
        return {}

    def _fake_apply(*_a, **_k):
        called["apply"] = True
        return {"applied": True, "path": str(diff), "files_changed": [], "warnings": [], "errors": []}

    def _fake_tests(*_a, **_k):
        called["tests"] = True
        return CommandResult(name="test", command="pytest -q", status="ok", exit_code=0)

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    exit_code = cli.main(["fix", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert called["apply"] is True
    assert called["tests"] is True
    assert "Apply result:" in out
    assert "Post-apply tests passed." in out
    assert "Next: run `aegis-code report` and `aegis-code status`." in out


def test_fix_diff_missing_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_run_task(**_: object):
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 2},
                "patch_diff": {"available": False, "path": None},
                "patch_quality": None,
            },
        )
        return {}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no apply")),
    )
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Fix summary:" in out
    assert "Verification command: pytest -q" in out
    assert "Failure count: 2" in out
    assert "Patch diff path: none" in out
    assert "No patch proposal available. Use report to inspect failures." in out
    assert "Next: run `aegis-code report`." in out


def test_fix_no_test_command_exits_with_unverified_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "\n".join(
            [
                "mode: balanced",
                "budget_per_task: 1.0",
                "models:",
                "  cheap: openai:gpt-4.1-nano",
                "  mid: openai:gpt-4.1-mini",
                "  premium: openai:gpt-4.1",
                "commands:",
                '  test: ""',
                '  lint: ""',
                "aegis:",
                '  base_url: "http://example.test"',
                "providers:",
                "  enabled: false",
                '  provider: "openai"',
                '  api_key_env: "OPENAI_API_KEY"',
                "patches:",
                "  generate_diff: false",
                "  max_context_chars: 12000",
                '  output_file: ".aegis/runs/latest.diff"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Fix summary:" in out
    assert "Verification command: none" in out
    assert "No test command detected. Aegis Code can inspect and plan, but cannot verify a fix yet." in out
    assert "Next: run `aegis-code init` or set `commands.test` in `.aegis/aegis-code.yml`." in out


def test_fix_confirm_apply_failure_reports_next_step(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )

    def _fake_run_task(**_: object):
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 1},
                "patch_diff": {"available": True, "path": str(diff)},
                "patch_quality": None,
            },
        )
        return {}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: {"applied": False, "path": str(diff), "files_changed": [], "warnings": [], "errors": ["x"]},
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no tests")),
    )
    exit_code = cli.main(["fix", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Apply result:" in out
    assert "Next: run `aegis-code apply --check .aegis/runs/latest.diff` and `aegis-code report`." in out


def test_fix_passes_project_context_to_runtime(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    captured = {"context": None}

    def _fake_run_task(**kwargs: object):
        options = kwargs["options"]
        captured["context"] = options.project_context
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 0},
                "patch_diff": {"available": False, "path": None},
                "patch_quality": None,
            },
        )
        return {}

    monkeypatch.setattr(
        "aegis_code.cli.load_runtime_context",
        lambda **_: {"available": True, "files": {}, "included_paths": [".aegis/context/project_summary.md"], "total_chars": 99},
    )
    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert captured["context"] is not None
    assert captured["context"]["available"] is True


def test_fix_low_budget_forces_cheapest_mode(tmp_path: Path, monkeypatch, capsys) -> None:
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
        _write_latest_json(
            tmp_path,
            {
                "failures": {"failure_count": 0},
                "patch_diff": {"available": False, "path": None},
                "patch_quality": None,
            },
        )
        return {}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert captured["mode"] == "cheapest"
