from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.models import CommandResult


def _ok_result() -> CommandResult:
    return CommandResult(name="tests", command="pytest -q", status="ok", exit_code=0, stdout="", stderr="", output_preview="", full_output="")


def _fail_result(signature: str) -> CommandResult:
    return CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=f"FAILED: {signature}",
    )


def _fail_pytest(nodeid: str, error: str, line: int) -> CommandResult:
    text = (
        "=========================== short test summary info ===========================\n"
        f"FAILED {nodeid} - {error}\n"
        f"{nodeid.split('::', 1)[0]}:{line}: {error}\n"
        "============================== 1 failed in 0.11s ==============================\n"
    )
    return CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=text,
    )


def test_fix_exits_when_tests_already_pass(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: _ok_result())
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))

    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "✔ tests already pass" in out


def test_fix_proposal_only_does_not_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: _fail_result("sig-a"))
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {
            "patch_diff": {"available": True, "path": str(diff)},
            "apply_safety": "HIGH",
        },
    )
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no apply")),
    )

    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch generated but not applied." in out
    assert "- aegis-code apply --confirm --run-tests" in out


def test_fix_confirm_applies_high_safety_patch(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    test_results = [_fail_result("sig-a"), _ok_result()]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    applied = {"called": False}

    def _fake_apply(path: Path, cwd=None):
        applied["called"] = True
        return {"applied": True, "path": str(path), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {
            "patch_diff": {"available": True, "path": str(diff)},
            "apply_safety": "HIGH",
        },
    )
    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)

    exit_code = cli.main(["fix", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert applied["called"] is True
    assert "Safety: HIGH" in out
    assert "✔ tests passed after fix" in out


def test_fix_blocks_low_or_blocked_safety_patch(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: _fail_result("sig-a"))
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {
            "patch_diff": {"available": True, "path": str(diff)},
            "apply_safety": "LOW",
        },
    )
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no apply")),
    )

    exit_code = cli.main(["fix", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Status: BLOCKED" in out
    assert "Reason: unsafe_patch" in out
    assert "Next:" in out
    assert "- aegis-code diff --full" in out


def test_fix_stops_on_repeated_failure_signature(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    test_results = [_fail_result("same-signature"), _fail_result("same-signature")]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {
            "patch_diff": {"available": True, "path": str(diff)},
            "apply_safety": "MEDIUM",
        },
    )
    monkeypatch.setattr(
        "aegis_code.cli.apply_patch_file",
        lambda *_a, **_k: {"applied": True, "path": str(diff), "files_changed": [], "warnings": [], "errors": []},
    )

    exit_code = cli.main(["fix", "--confirm", "--max-cycles", "2"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Failure signature repeated. Stopping to avoid loop." in out
    assert "No further files changed." in out


def test_fix_stops_when_same_failure_test_and_assertion_remain_after_apply(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    test_results = [
        _fail_pytest("tests/test_client.py::test_action", "AssertionError: 'test_action' not found in []", 120),
        _fail_pytest("tests/test_client.py::test_action", "AssertionError: 'test_action' not found in []", 245),
    ]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    apply_calls = {"count": 0}

    def _fake_apply(*_a, **_k):
        apply_calls["count"] += 1
        return {"applied": True, "path": str(diff), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"},
    )
    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)

    exit_code = cli.main(["fix", "--confirm", "--max-cycles", "3"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Tests still failing after applied fix." in out
    assert "Failure signature repeated. Stopping to avoid loop." in out
    assert "No further files changed." in out
    assert apply_calls["count"] == 1


def test_fix_continues_when_failure_signature_changes(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")

    test_results = [
        _fail_pytest("tests/test_client.py::test_action", "AssertionError: action missing", 12),
        _fail_pytest("tests/test_client.py::test_new_action", "AssertionError: new action missing", 30),
        _ok_result(),
    ]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    apply_calls = {"count": 0}

    def _fake_apply(*_a, **_k):
        apply_calls["count"] += 1
        return {"applied": True, "path": str(diff), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr(
        "aegis_code.cli.run_task",
        lambda **_: {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"},
    )
    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)

    exit_code = cli.main(["fix", "--confirm", "--max-cycles", "3"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Cycle 2/3" in out
    assert "✔ tests passed after fix" in out
    assert apply_calls["count"] == 2


def test_fix_rejects_invalid_max_cycles(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["fix", "--max-cycles", "0"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert "--max-cycles must be between 1 and 5" in out
