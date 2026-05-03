from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.models import CommandResult
from aegis_code.patches.diff_inspector import inspect_diff


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


def _fail_pytest_assertion_diff(nodeid: str, expected: str, actual: str, line: int = 10) -> CommandResult:
    file_path = nodeid.split("::", 1)[0]
    text = (
        "=================================== FAILURES ===================================\n"
        f"_____________________ {nodeid.split('::')[-1]} _____________________\n"
        f"E       assert \"{actual}\" == \"{expected}\"\n"
        "AssertionError:\n"
        f"- {expected}\n"
        f"+ {actual}\n"
        "=========================== short test summary info ===========================\n"
        f"FAILED {nodeid} - AssertionError\n"
        f"{file_path}:{line}: AssertionError\n"
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


def test_fix_prompt_targets_failing_test_file_for_assertion_mismatch(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff.parent.mkdir(parents=True, exist_ok=True)
    diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
    captured = {"task": ""}
    test_results = [
        _fail_pytest("tests/test_client.py::test_action", "AssertionError: expected x got y", 10),
    ]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    def _fake_run_task(**kwargs):
        options = kwargs["options"]
        captured["task"] = options.task
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert "fix failing tests in tests/test_client.py" in captured["task"]
    assert "prefer updating the failing test assertion" in captured["task"]
    assert "target failing test tests/test_client.py::test_action" in captured["task"]
    assert "assertion mismatch:" in captured["task"]
    assert "do not use placeholder hunk headers such as @@ ... @@." in captured["task"]


def test_deterministic_assertion_fix_simple_case(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_aegis_intentional_semantic_failure():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest_assertion_diff(
            "tests/test_client.py::test_aegis_intentional_semantic_failure",
            "wrong",
            "scope=llm actions=0 trace_steps=0 used_fallback=no",
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch generated but not applied." in out
    diff_path = tmp_path / ".aegis" / "runs" / "latest.diff"
    assert diff_path.exists()
    inspected = inspect_diff(diff_path.read_text(encoding="utf-8"), cwd=tmp_path)
    summary = inspected.get("summary", {})
    assert summary.get("additions") == 1
    assert summary.get("deletions") == 1


def test_deterministic_assertion_fix_refuses_complex_case(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("def test_one():\n    assert True\n", encoding="utf-8")
    calls = {"run_task": 0}
    results = [
        _fail_pytest_assertion_diff("tests/test_client.py::test_one", "a", "b"),
    ]

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: results[0])

    def _fake_parse(_text: str):
        return {
            "failed_tests": [
                {"test_name": "tests/test_client.py::test_one", "file": "tests/test_client.py", "error": "AssertionError"},
                {"test_name": "tests/test_client.py::test_two", "file": "tests/test_client.py", "error": "AssertionError"},
            ],
            "failure_count": 2,
        }

    monkeypatch.setattr("aegis_code.cli.parse_pytest_output", _fake_parse)

    def _fake_run_task(**_kwargs):
        calls["run_task"] += 1
        diff = tmp_path / ".aegis" / "runs" / "latest.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert calls["run_task"] == 1


def test_deterministic_assertion_fix_refuses_non_string_assertion(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_number():\n"
        "    value = 1\n"
        "    assert value == 2\n",
        encoding="utf-8",
    )
    calls = {"run_task": 0}
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest_assertion_diff("tests/test_client.py::test_number", "2", "1"),
    )

    def _fake_run_task(**_kwargs):
        calls["run_task"] += 1
        diff = tmp_path / ".aegis" / "runs" / "latest.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert calls["run_task"] == 1


def test_deterministic_fix_triggers_for_basic_assertion(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_aegis_intentional_semantic_failure():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest_assertion_diff(
            "tests/test_client.py::test_aegis_intentional_semantic_failure",
            "wrong",
            "scope=llm actions=0 trace_steps=0 used_fallback=no",
        ),
    )
    calls = {"run_task": 0}

    def _fake_run_task(**_kwargs):
        calls["run_task"] += 1
        diff = tmp_path / ".aegis" / "runs" / "latest.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch generated but not applied." in out
    assert "actual_value_extracted: yes" in out
    assert calls["run_task"] == 0


def test_deterministic_fix_handles_pytest_diff_format(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_diff_format():\n"
        "    value = 'x'\n"
        "    assert value == \"wrong\"\n",
        encoding="utf-8",
    )
    failure = CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=(
            "=================================== FAILURES ===================================\n"
            "______________________________ test_diff_format ______________________________\n"
            "E       assert 'scope=llm actions=0 trace_steps=0 used_fallback=no' == 'wrong'\n"
            "AssertionError:\n"
            "- wrong\n"
            "+ scope=llm actions=0 trace_steps=0 used_fallback=no\n"
            "=========================== short test summary info ===========================\n"
            "FAILED tests/test_client.py::test_diff_format - AssertionError\n"
            "tests/test_client.py:3: AssertionError\n"
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: failure)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "actual_value_extracted: yes" in out
    assert "Patch generated but not applied." in out


def test_deterministic_fix_handles_truncated_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_truncated():\n"
        "    result = 'scope=llm actions=0 trace_steps=0 used_fallback=no'\n"
        "    assert result == \"wrong\"\n",
        encoding="utf-8",
    )
    failure = CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=(
            "=================================== FAILURES ===================================\n"
            "E       assert 'scope=llm actions=0 trace_steps=0 used_fallback=no' == 'wrong'\n"
            "AssertionError:\n"
            "- wrong\n"
            "+ ...truncated...\n"
            "FAILED tests/test_client.py::test_truncated - AssertionError\n"
            "tests/test_client.py:3: AssertionError\n"
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: failure)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "actual_value_extracted: yes" in out
    assert "Patch generated but not applied." in out


def test_deterministic_fix_falls_back_when_no_assert_found(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_without_assert_eq():\n"
        "    raise AssertionError('fail')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest("tests/test_client.py::test_without_assert_eq", "AssertionError", 2),
    )
    calls = {"run_task": 0}

    def _fake_run_task(**_kwargs):
        calls["run_task"] += 1
        diff = tmp_path / ".aegis" / "runs" / "latest.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "assertion_line_found: no" in out
    assert calls["run_task"] == 1


def test_extract_actual_from_truncated_pytest_output(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_truncated_extract():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    result = CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=(
            "=================================== FAILURES ===================================\n"
            "E AssertionError: assert 'scope=llm ac...d_fallback=no' == 'wrong'\n"
            "FAILED tests/test_client.py::test_truncated_extract - AssertionError\n"
            "tests/test_client.py:4: AssertionError\n"
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: result)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "actual_value_extracted: yes" in out
    assert "Patch generated but not applied." in out


def test_deterministic_fix_triggers_with_truncated_actual(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_truncated_trigger():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    result = CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=(
            "=================================== FAILURES ===================================\n"
            "E AssertionError: assert 'scope=llm ac...d_fallback=no' == 'wrong'\n"
            "FAILED tests/test_client.py::test_truncated_trigger - AssertionError\n"
            "tests/test_client.py:4: AssertionError\n"
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: result)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "single_failure: yes" in out
    assert "is_assertion_error: yes" in out
    assert "Patch generated but not applied." in out
    diff_path = tmp_path / ".aegis" / "runs" / "latest.diff"
    assert diff_path.exists()
    diff_text = diff_path.read_text(encoding="utf-8")
    assert "scope=llm actions=0 trace_steps=0 used_fallback=no" in diff_text


def test_deterministic_fix_uses_fallback_when_full_actual_unavailable(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_fallback_case():\n"
        "    value = 1\n"
        "    assert value == 2\n",
        encoding="utf-8",
    )
    result = CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=(
            "=================================== FAILURES ===================================\n"
            "E AssertionError: assert 1 == 2\n"
            "FAILED tests/test_client.py::test_fallback_case - AssertionError\n"
            "tests/test_client.py:3: AssertionError\n"
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_configured_tests", lambda *_a, **_k: result)
    calls = {"run_task": 0}

    def _fake_run_task(**_kwargs):
        calls["run_task"] += 1
        diff = tmp_path / ".aegis" / "runs" / "latest.diff"
        diff.parent.mkdir(parents=True, exist_ok=True)
        diff.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
        return {"patch_diff": {"available": True, "path": str(diff)}, "apply_safety": "HIGH"}

    monkeypatch.setattr("aegis_code.cli.run_task", _fake_run_task)
    exit_code = cli.main(["fix"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "actual_value_extracted: no" in out
    assert calls["run_task"] == 1


def test_deterministic_assertion_fix_writes_high_safety_latest_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_metadata_written():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest_assertion_diff(
            "tests/test_client.py::test_metadata_written",
            "wrong",
            "scope=llm actions=0 trace_steps=0 used_fallback=no",
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    exit_code = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    latest_json = tmp_path / ".aegis" / "runs" / "latest.json"
    assert latest_json.exists()
    payload = json.loads(latest_json.read_text(encoding="utf-8"))
    assert payload.get("apply_safety") == "HIGH"
    assert payload.get("task") == "fix failing tests"
    assert payload.get("status") == "fix_proposal_generated"
    patch_diff = payload.get("patch_diff", {})
    assert patch_diff.get("available") is True
    assert patch_diff.get("status") == "generated"
    assert str(patch_diff.get("path", "")).replace("\\", "/").endswith(".aegis/runs/latest.diff")
    assert isinstance(patch_diff.get("validation_result"), dict)
    assert patch_diff.get("syntactic_valid") is True
    patch_quality = payload.get("patch_quality", {})
    assert patch_quality.get("confidence") == 0.95
    assert patch_quality.get("reason") == "deterministic_assertion_fix"


def test_apply_check_allows_deterministic_high_safety_fix(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_apply_check_allowed():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda *_a, **_k: _fail_pytest_assertion_diff(
            "tests/test_client.py::test_apply_check_allowed",
            "wrong",
            "scope=llm actions=0 trace_steps=0 used_fallback=no",
        ),
    )
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    fix_exit = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert fix_exit == 0
    check_exit = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert check_exit == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_confirm_allows_deterministic_high_safety_fix(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    test_file = tmp_path / "tests" / "test_client.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text(
        "def test_apply_confirm_allowed():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == \"wrong\"\n",
        encoding="utf-8",
    )
    test_results = [
        _fail_pytest_assertion_diff(
            "tests/test_client.py::test_apply_confirm_allowed",
            "wrong",
            "scope=llm actions=0 trace_steps=0 used_fallback=no",
        ),
        _ok_result(),
    ]

    def _fake_tests(*_a, **_k):
        return test_results.pop(0)

    monkeypatch.setattr("aegis_code.cli.run_configured_tests", _fake_tests)
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no provider call")))
    fix_exit = cli.main(["fix"])
    _ = capsys.readouterr().out
    assert fix_exit == 0
    apply_exit = cli.main(["apply", "--confirm", "--run-tests"])
    out = capsys.readouterr().out
    assert apply_exit == 0
    assert "- Tests: passed" in out
    updated = test_file.read_text(encoding="utf-8")
    assert "assert result.debug_summary() == \"scope=llm actions=0 trace_steps=0 used_fallback=no\"" in updated
