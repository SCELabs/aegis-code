from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.providers.openai_provider import generate_patch_diff_openai
from aegis_code.report import render_markdown_report
from aegis_code.runtime import (
    TaskOptions,
    _aegis_corrective_control,
    build_run_payload,
    is_constructive_task,
    run_task,
)
from tests.helpers import command_result_from_output, pytest_output_fail, pytest_output_pass


class _Client:
    def __init__(self) -> None:
        self.decision = AegisDecision(
            model_tier="mid",
            context_mode="focused",
            max_retries=0,
            allow_escalation=False,
            execution={},
        )

    def step_scope(self, **_: object) -> AegisDecision:
        return self.decision


def test_provider_disabled_by_default(tmp_path: Path) -> None:
    payload = build_run_payload(
        options=TaskOptions(task="x", dry_run=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is False


def test_missing_api_key_returns_unavailable(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = generate_patch_diff_openai(
        model="openai:gpt-4.1-mini",
        task="fix",
        failures={"failure_count": 1, "failed_tests": [{"test_name": "x", "file": "tests/test_x.py"}]},
        context={"files": [{"path": "tests/test_x.py", "content": "x"}]},
        patch_plan={"proposed_changes": [{"file": "x"}]},
        aegis_execution={},
        api_key_env="OPENAI_API_KEY",
        max_context_chars=1000,
    )
    assert result["available"] is False
    assert "Missing API key env" in str(result["error"])


def test_invalid_diff_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    fake_openai = types.ModuleType("openai")

    class _Message:
        content = "not a diff output"

    class _Choice:
        message = _Message()

    class _Completions:
        @staticmethod
        def create(**_: object):
            class _Resp:
                choices = [_Choice()]

            return _Resp()

    class _Chat:
        completions = _Completions()

    class _ClientImpl:
        def __init__(self, **_: object) -> None:
            self.chat = _Chat()

    fake_openai.OpenAI = _ClientImpl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    result = generate_patch_diff_openai(
        model="openai:gpt-4.1-mini",
        task="fix",
        failures={"failure_count": 1, "failed_tests": [{"test_name": "x", "file": "tests/test_x.py"}]},
        context={"files": [{"path": "tests/test_x.py", "content": "x"}]},
        patch_plan={"proposed_changes": [{"file": "x"}]},
        aegis_execution={},
        api_key_env="OPENAI_API_KEY",
        max_context_chars=1000,
    )
    assert result["available"] is False
    assert "unified diff" in str(result["error"]).lower()


def test_propose_patch_triggers_attempt_and_writes_diff(monkeypatch, tmp_path: Path) -> None:
    source_file = tmp_path / "aegis_code" / "sample.py"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    before = source_file.read_text(encoding="utf-8")

    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )

    payload = build_run_payload(
        options=TaskOptions(task="x", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    patch_diff = payload["patch_diff"]
    assert patch_diff["attempted"] is True
    assert patch_diff["available"] is True
    assert patch_diff["path"]
    assert Path(patch_diff["path"]).exists()
    assert payload["patch_quality"] is not None
    assert payload["patch_quality"]["grounded"] is True
    assert payload["patch_quality"]["confidence"] > 0.0
    report = render_markdown_report(payload)
    assert "## Patch Diff Proposal" in report
    assert "## Patch Quality" in report
    assert "Provider: `openai`" in report
    assert "Path: `" in report
    assert source_file.read_text(encoding="utf-8") == before
    assert Path(patch_diff["path"]).read_text(encoding="utf-8").startswith("diff --git")


def test_no_provider_call_when_tests_pass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_pass(), status="ok", exit_code=0
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _boom(**_: object):
        raise AssertionError("provider should not be called")

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _boom)
    payload = build_run_payload(
        options=TaskOptions(task="x", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is False


def test_task_driven_patch_plan_when_tests_pass(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(task="implement notes cli", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["failures"]["failure_count"] == 0
    assert payload["task_driven_patch_proposal"] is True
    assert payload["patch_plan"]["proposed_changes"]


def test_task_driven_patch_diff_attempt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "Provider unavailable",
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="implement notes cli", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is True


def test_no_patch_without_flag(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(task="implement notes cli", propose_patch=False),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["task_driven_patch_proposal"] is False
    assert payload["patch_plan"]["proposed_changes"] == []
    assert payload["patch_diff"]["attempted"] is False


def test_provider_unavailable_task_patch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(task="implement notes cli", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is True
    assert payload["patch_diff"]["status"] == "unavailable"
    assert payload["patch_diff"]["available"] is False
    assert payload["patch_diff"]["error"]
    report = render_markdown_report(payload)
    assert "## Task-Driven Patch Proposal" in report


def test_failing_tests_no_propose_patch_no_attempt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(task="x", propose_patch=False),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is False
    assert payload["patch_quality"] is None


def test_failing_tests_propose_patch_missing_key_attempted_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(
        options=TaskOptions(task="x", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    patch_diff = payload["patch_diff"]
    assert patch_diff["attempted"] is True
    assert patch_diff["available"] is False
    assert patch_diff["error"]
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_invalid_provider_diff_no_file_written(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "Provider output did not look like a unified diff.",
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="x", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    patch_diff = payload["patch_diff"]
    assert patch_diff["attempted"] is True
    assert patch_diff["status"] == "unavailable"
    assert patch_diff["available"] is False
    assert "unified diff" in str(patch_diff["error"]).lower()
    assert patch_diff["path"] is None
    assert payload["patch_quality"] is None
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_failure_with_sll_and_patch_diff_report_state(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(
            pytest_output_fail(), status="failed", exit_code=1
        ),
    )
    monkeypatch.setattr(
        "aegis_code.runtime.analyze_failures_sll",
        lambda _text: {
            "available": True,
            "regime": "fragmentation",
            "fragmentation_risk": 0.9,
            "collapse_risk": 0.0,
            "drift_risk": 0.7,
            "stable_random_risk": 0.0,
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )

    payload = run_task(options=TaskOptions(task="x", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["failures"]["failure_count"] > 0
    assert "test_failure" in payload["symptoms"]
    assert "fragmented_output" in payload["symptoms"]
    assert payload["sll_analysis"]["available"] is True
    assert payload["patch_plan"]["proposed_changes"]
    assert payload["patch_diff"]["attempted"] is True
    assert payload["patch_quality"] is not None
    assert payload["patch_quality"]["relevant_files"] is True

    report_path = tmp_path / ".aegis" / "runs" / "latest.md"
    report = report_path.read_text(encoding="utf-8")
    assert "## Final Failure State" in report
    assert "## Structural Analysis" in report
    assert "Regime: `fragmentation`" in report
    assert "## Proposed Fix Plan" in report
    assert "## Patch Diff Proposal" in report


def test_task_driven_diff_without_git_header_is_normalized(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    (tmp_path / "main.py").write_text("print('x')\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-print('x')\n+print('y')\n",
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="implement feature", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    diff_path = payload["patch_diff"]["path"]
    assert diff_path
    text = Path(diff_path).read_text(encoding="utf-8")
    assert text.startswith("diff --git a/main.py b/main.py\n")


def test_is_constructive_task_test_generation_phrases() -> None:
    assert is_constructive_task("add tests for saving notes") is True
    assert is_constructive_task("write tests for save_note_to_file") is True
    assert is_constructive_task("increase coverage for notes") is True
    assert is_constructive_task("test for edge cases in note saving") is True
    assert is_constructive_task("run tests") is False
    assert is_constructive_task("check tests") is False


def test_task_driven_test_writing_uses_patch_plan_and_attempts_diff(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("def save_note_to_file():\n    return True\n", encoding="utf-8")
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "Provider unavailable",
        },
    )

    payload = build_run_payload(
        options=TaskOptions(task="add tests for saving notes", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["task_driven_patch_proposal"] is True
    assert payload["patch_plan"]["proposed_changes"]
    assert any(
        isinstance(item, dict) and item.get("reason") == "test_generation_task" and item.get("file") == "tests/test_cli.py"
        for item in payload["patch_plan"]["proposed_changes"]
    )
    assert payload["patch_plan"].get("target_file") == "tests/test_cli.py"
    assert not any(
        isinstance(item, dict) and item.get("reason") == "entrypoint_integration"
        for item in payload["patch_plan"]["proposed_changes"]
    )
    assert payload["patch_diff"]["attempted"] is True


def test_feature_task_may_add_entrypoint_plan_item(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "Provider unavailable",
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="implement cli command", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert any(
        isinstance(item, dict) and item.get("reason") == "entrypoint_integration"
        for item in payload["patch_plan"]["proposed_changes"]
    )


def test_test_task_requests_full_file_diff(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    captured: dict[str, object] = {}

    def _provider(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "available": False,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "",
            "error": "Provider unavailable",
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_cli.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    payload = build_run_payload(
        options=TaskOptions(task="add tests for save_note_to_file only; do not modify source files", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_plan"]["task_type"] == "test_generation"
    plan = captured.get("patch_plan")
    assert isinstance(plan, dict)
    assert plan.get("target_file") == "tests/test_cli.py"


def test_generated_diff_is_single_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_cli.py b/tests/test_cli.py\n--- a/tests/test_cli.py\n+++ b/tests/test_cli.py\n@@ -1,1 +1,2 @@\n-a\n+b\n+c\n",
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add tests for cli behavior", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    preview = str(payload["patch_diff"].get("preview", ""))
    assert preview.count("diff --git ") == 1
    assert "diff --git a/tests/test_cli.py b/tests/test_cli.py" in preview


def test_run_tests_task_is_not_constructive_no_patch_attempt(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _boom(**_: object):
        raise AssertionError("provider should not be called")

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _boom)
    payload = build_run_payload(
        options=TaskOptions(task="run tests", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["task_driven_patch_proposal"] is False
    assert payload["patch_diff"]["attempted"] is False


def test_test_generation_patch_touching_only_tests_has_no_unexpected_source_issue(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_cli.py b/tests/test_cli.py\n--- a/tests/test_cli.py\n+++ b/tests/test_cli.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add tests for cli behavior", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_quality"] is not None
    assert "unexpected_source_modification_for_test_task" not in payload["patch_quality"]["issues"]


def test_test_generation_patch_touching_source_adds_issue_and_lowers_confidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )
    payload = build_run_payload(
        options=TaskOptions(task="add tests for cli behavior", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_quality"] is not None
    assert "unexpected_source_modification_for_test_task" in payload["patch_quality"]["issues"]
    assert payload["patch_quality"]["confidence"] < 0.7


def test_invalid_diff_triggers_regeneration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 2
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["status"] == "generated"


def test_low_quality_triggers_regeneration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": "diff --git a/docs/notes.md b/docs/notes.md\n--- a/docs/notes.md\n+++ b/docs/notes.md\n@@ -1 +1 @@\n-a\n+b\n",
                "error": None,
            }
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 2
    assert payload["patch_diff"]["regeneration_attempted"] is True


def test_test_task_source_modification_triggers_regeneration(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
                "error": None,
            }
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_cli.py b/tests/test_cli.py\n--- a/tests/test_cli.py\n+++ b/tests/test_cli.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(task="add tests for cli behavior", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert calls["count"] == 2
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["regeneration"]["reason"] in {"test_source_modification", "low_quality"}


def test_regeneration_improves_validity(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["validation_result"]["valid"] is True
    assert payload["patch_diff"]["status"] == "generated"


def test_regeneration_only_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 2
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["status"] == "invalid"


def test_no_regeneration_when_valid(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 1
    assert payload["patch_diff"]["regeneration_attempted"] is False


def test_invalid_final_diff_writes_invalid_diff_not_latest(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1,1 +1,1 @@\n-a\n+b\n+c\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["available"] is False
    assert payload["patch_diff"]["error"] == "hunk_count_mismatch"
    assert payload["patch_diff"]["validation_errors"]
    invalid_path = payload["patch_diff"]["invalid_diff_path"]
    assert invalid_path
    assert Path(invalid_path).exists()
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_invalid_final_diff_has_no_high_quality(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1,1 +1,1 @@\n-a\n+b\n+c\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_quality"] is None
    report = render_markdown_report(payload)
    assert "Patch quality: invalid (not evaluated)" in report


def test_unavailable_provider_remains_unavailable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "unavailable"


def test_valid_final_diff_writes_latest_diff(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["path"]
    assert Path(payload["patch_diff"]["path"]).exists()
    assert payload["patch_quality"] is not None


def test_valid_diff_sets_syntactic_valid_true(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_example.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1,2 +1,2 @@\n-def test_old():\n-    assert True\n+def test_new():\n+    assert True\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["syntactic_valid"] is True
    assert payload["patch_diff"]["syntactic_error"] is None


def test_truncated_function_sets_syntactic_valid_false(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_example.py").write_text("def test_old():\n    assert True\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1,2 +1,2 @@\n-def test_old():\n-    assert True\n+def test_new(\n+    assert True\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["syntactic_valid"] is False
    assert payload["patch_diff"]["syntactic_error"]


def test_valid_diff_generation_removes_stale_latest_invalid_diff(monkeypatch, tmp_path: Path) -> None:
    stale = tmp_path / ".aegis" / "runs" / "latest.invalid.diff"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("stale invalid diff", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert not stale.exists()


def test_invalid_diff_generation_preserves_latest_invalid_diff(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1,1 +1,1 @@\n-a\n+b\n+c\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "invalid"
    invalid_path = payload["patch_diff"]["invalid_diff_path"]
    assert invalid_path
    assert Path(invalid_path).exists()


def test_corrective_control_reason_displayed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="fix tests", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["corrective_control_status"] in {
        "applied",
        "not_available",
        "client_error",
        "no_guidance_returned",
        "disabled_by_config",
    }


def test_corrective_control_step_signature_used(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Auto:
        def step(self, **kwargs):
            captured.update(kwargs)
            return {"constraints": ["keep hunks valid"]}

    class _ClientImpl:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self):
            return _Auto()

    fake_aegis = types.ModuleType("aegis")
    fake_aegis.AegisClient = _ClientImpl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)

    result = _aegis_corrective_control(
        task="fix tests",
        task_type="test_generation",
        issues=["low_quality"],
        validation_errors=["hunk_count_mismatch"],
        context_paths=["tests/test_cli.py"],
        base_url="http://example.test",
    )
    assert result["status"] == "applied"
    assert captured.get("step_name") == "patch_regeneration_correction"
    assert isinstance(captured.get("step_input"), dict)
    assert "input" not in captured


def test_corrective_control_client_error_contains_exception_reason(monkeypatch) -> None:
    class _Auto:
        def step(self, **_: object):
            raise RuntimeError("simulated control failure")

    class _ClientImpl:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self):
            return _Auto()

    fake_aegis = types.ModuleType("aegis")
    fake_aegis.AegisClient = _ClientImpl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = _aegis_corrective_control(
        task="fix tests",
        task_type="test_generation",
        issues=["low_quality"],
        validation_errors=["hunk_count_mismatch"],
        context_paths=["tests/test_cli.py"],
        base_url="http://example.test",
    )
    assert result["status"] == "client_error"
    assert "simulated control failure" in str(result["error"])


def test_corrective_control_no_guidance_returned_distinct_from_client_error(monkeypatch) -> None:
    class _Auto:
        def step(self, **_: object):
            return {}

    class _ClientImpl:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self):
            return _Auto()

    fake_aegis = types.ModuleType("aegis")
    fake_aegis.AegisClient = _ClientImpl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = _aegis_corrective_control(
        task="fix tests",
        task_type="test_generation",
        issues=["low_quality"],
        validation_errors=["hunk_count_mismatch"],
        context_paths=["tests/test_cli.py"],
        base_url="http://example.test",
    )
    assert result["status"] == "no_guidance_returned"
    assert result["reason"] == "no_guidance_returned"
