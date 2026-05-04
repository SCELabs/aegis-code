from __future__ import annotations

import json
from pathlib import Path

from aegis_code.budget import set_budget
from aegis_code.config import ensure_project_files
from aegis_code.runtime import TaskOptions, build_run_payload
from aegis_code.short_circuit import should_skip_provider
from tests.helpers import command_result_from_output, pytest_output_fail


def _write_latest(cwd: Path, payload: dict) -> None:
    runs = cwd / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")


def test_short_circuit_test_only_task_skips_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    decision = should_skip_provider(TaskOptions(task="run tests", propose_patch=True), tmp_path)
    assert decision["skip"] is True
    assert decision["reason"] == "verification_only"


def test_short_circuit_no_verification_skips_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    cfg_path = tmp_path / ".aegis" / "aegis-code.yml"
    cfg_path.write_text(cfg_path.read_text(encoding="utf-8").replace('test: "pytest -q"', 'test: ""'), encoding="utf-8")
    decision = should_skip_provider(TaskOptions(task="fix tests", propose_patch=True), tmp_path)
    assert decision["skip"] is True
    assert decision["reason"] == "no_verification_available"


def test_short_circuit_existing_valid_diff_skips_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    test_file = tmp_path / "tests" / "test_example.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    test_file.write_text("a\n", encoding="utf-8")
    latest_diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    latest_diff.parent.mkdir(parents=True, exist_ok=True)
    latest_diff.write_text(
        "diff --git a/tests/test_example.py b/tests/test_example.py\n"
        "--- a/tests/test_example.py\n"
        "+++ b/tests/test_example.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n",
        encoding="utf-8",
    )
    decision = should_skip_provider(TaskOptions(task="implement feature", propose_patch=True), tmp_path)
    assert decision["skip"] is True
    assert decision["reason"] == "existing_patch_available"


def test_short_circuit_repeated_failure_skips_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    payload = {
        "status": "completed_tests_failed",
        "patch_diff": {"attempted": True},
        "initial_failures": {"failure_count": 1, "failed_tests": [{"test_name": "tests/test_x.py::test_a", "file": "tests/test_x.py", "error": "AssertionError: x"}]},
        "final_failures": {"failure_count": 1, "failed_tests": [{"test_name": "tests/test_x.py::test_a", "file": "tests/test_x.py", "error": "AssertionError: x"}]},
    }
    _write_latest(tmp_path, payload)
    decision = should_skip_provider(TaskOptions(task="add feature", propose_patch=True), tmp_path)
    assert decision["skip"] is True
    assert decision["reason"] == "repeated_failure"


def test_short_circuit_budget_exceeded_skips_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    set_budget(0.0, cwd=tmp_path)
    decision = should_skip_provider(TaskOptions(task="add feature", propose_patch=True), tmp_path)
    assert decision["skip"] is True
    assert decision["reason"] == "budget_exceeded"


def test_short_circuit_no_rule_allows_provider(tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    decision = should_skip_provider(TaskOptions(task="add feature", propose_patch=True), tmp_path)
    assert decision["skip"] is False
    assert decision["reason"] == "none"


def test_provider_called_when_no_short_circuit_rule(monkeypatch, tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    called = {"provider": False}

    def _provider(**_: object) -> dict[str, object]:
        called["provider"] = True
        return {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "unavailable",
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    _ = build_run_payload(options=TaskOptions(task="add endpoint", propose_patch=True), cwd=tmp_path)
    assert called["provider"] is True


def test_runtime_payload_marks_provider_skipped(monkeypatch, tmp_path: Path) -> None:
    ensure_project_files(cwd=tmp_path, force=True)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", lambda **_: (_ for _ in ()).throw(AssertionError("provider should skip")))
    payload = build_run_payload(options=TaskOptions(task="run tests", propose_patch=True), cwd=tmp_path)
    assert payload["status"] == "skipped_provider"
    assert payload["provider_skipped"] is True
    assert payload["skip_reason"] == "verification_only"
