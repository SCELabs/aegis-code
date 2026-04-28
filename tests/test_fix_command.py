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
    assert "Tests passed. No action required." in out


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
    assert "Patch proposal:" in out
    assert "Use --confirm to apply this patch." in out


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
    assert "Post-apply tests passed." in out


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
    assert "No patch proposal available. Use report to inspect failures." in out

