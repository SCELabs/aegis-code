from __future__ import annotations

import sys
import time
import types
from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.providers.openai_provider import generate_patch_diff_openai
from aegis_code.providers.base import build_diff_prompt
from aegis_code.report import render_markdown_report
from aegis_code.runtime import (
    TaskOptions,
    _aegis_corrective_control,
    build_run_payload,
    classify_task_type,
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


def test_mixed_task_classifies_as_implementation_with_tests() -> None:
    assert classify_task_type("add a helpers module with a slugify(text) function and tests for it") == "implementation_with_tests"


def test_test_only_task_remains_test_generation() -> None:
    assert classify_task_type("add tests for save_note_to_file only; do not modify source files") == "test_generation"


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


def test_mixed_task_patch_plan_includes_helpers_and_tests(monkeypatch, tmp_path: Path) -> None:
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
    payload = build_run_payload(
        options=TaskOptions(task="add a helpers module with a slugify(text) function and tests for it", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_plan"]["task_type"] == "implementation_with_tests"
    files = [str(item.get("file", "")) for item in payload["patch_plan"]["proposed_changes"] if isinstance(item, dict)]
    assert "src/helpers.py" in files
    assert "tests/test_helpers.py" in files
    plan = captured.get("patch_plan")
    assert isinstance(plan, dict)
    assert sorted(plan.get("allowed_targets", [])) == ["src/helpers.py", "tests/test_helpers.py"]


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


def test_impl_with_tests_prompt_includes_allowed_targets() -> None:
    prompt = build_diff_prompt(
        task="add helpers module and tests",
        failures={},
        context={"files": []},
        patch_plan={
            "task_type": "implementation_with_tests",
            "allowed_targets": ["src/helpers.py", "tests/test_helpers.py"],
            "proposed_changes": [],
        },
        aegis_execution={},
    )
    assert "Create or modify only the planned files." in prompt
    assert "Allowed targets: src/helpers.py, tests/test_helpers.py" in prompt
    assert "Prefer modifying tests only." not in prompt
    assert "Do not modify source files unless explicitly requested." not in prompt


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
    assert payload["patch_diff"]["regenerated"] is False


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
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "syntactic_invalid"
    assert payload["patch_diff"]["syntactic_valid"] is False
    assert payload["patch_diff"]["syntactic_error"]
    assert payload["patch_quality"] is None


def test_large_diff_marks_invalid_with_excessive_diff_size(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("x=1\n", encoding="utf-8")
    added = "".join(f"+line{i} = {i}\n" for i in range(900))
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
            "diff": "diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1 +1,900 @@\n-x=1\n" + added,
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="implement feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "excessive_diff_size"
    assert payload["patch_quality"] is None


def test_normal_diff_still_generated(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text("x=1\n", encoding="utf-8")
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
            "diff": "diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-x=1\n+x=2\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="implement feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["error"] is None
    assert payload["patch_quality"] is not None


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


def test_provider_generation_stage_shown_before_provider_call(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    progress: list[str] = []

    def _provider(**_: object) -> dict[str, object]:
        assert any("generating provider diff" in msg for msg in progress)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(
            task="fix tests",
            propose_patch=True,
            progress_callback=lambda message: progress.append(str(message)),
        ),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["attempted"] is True


def test_plan_consistency_detects_missing_target(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "implement feature",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
                {"file": "src/helpers.py", "change_type": "create", "description": "helper", "reason": "feature"},
            ],
        },
    )
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
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is False
    assert payload["patch_diff"]["plan_missing_targets"] == ["src/helpers.py"]
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "plan_inconsistent"
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_quality"] is None


def test_plan_consistency_aligned(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "implement feature",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
            ],
        },
    )
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
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is True
    assert payload["patch_diff"]["plan_missing_targets"] == []


def test_plan_consistency_partial_multifile_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "implement feature",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
                {"file": "README.md", "change_type": "modify", "description": "docs", "reason": "feature"},
                {"file": "src/helpers.py", "change_type": "create", "description": "helper", "reason": "feature"},
            ],
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n"
                "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-a\n+b\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is False
    assert payload["patch_diff"]["plan_missing_targets"] == ["src/helpers.py"]


def test_plan_consistency_detects_missing_helpers_test_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "add helper module and tests",
            "confidence": 0.7,
            "task_type": "implementation_with_tests",
            "proposed_changes": [
                {"file": "src/helpers.py", "change_type": "create", "description": "helpers", "reason": "feature"},
                {"file": "tests/test_helpers.py", "change_type": "create", "description": "tests", "reason": "feature"},
            ],
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/helpers.py b/src/helpers.py\n--- /dev/null\n+++ b/src/helpers.py\n@@ -0,0 +1,2 @@\n+def slugify(text):\n+    return text\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is False
    assert "tests/test_helpers.py" in payload["patch_diff"]["plan_missing_targets"]


def test_plan_consistency_detects_missing_inferred_helpers_from_import(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "implement feature",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
            ],
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+from src.helpers import build_helper\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is False
    assert "src/helpers.py" in payload["patch_diff"]["plan_missing_targets"]
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "plan_inconsistent"
    assert payload["patch_quality"] is None


def test_plan_consistency_detects_missing_inferred_helpers_from_strategy(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "add module for helper functions",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
            ],
        },
    )
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
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is False
    assert "src/helpers.py" in payload["patch_diff"]["plan_missing_targets"]
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "plan_inconsistent"
    assert payload["patch_quality"] is None


def test_plan_consistency_helpers_present_no_mismatch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_plan",
        lambda *_args, **_kwargs: {
            "strategy": "create module for helpers",
            "confidence": 0.7,
            "task_type": "general",
            "proposed_changes": [
                {"file": "src/main.py", "change_type": "modify", "description": "main", "reason": "feature"},
            ],
        },
    )
    monkeypatch.setattr(
        "aegis_code.runtime.generate_patch_diff",
        lambda **_: {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+from src.helpers import build_helper\n"
                "diff --git a/src/helpers.py b/src/helpers.py\n--- /dev/null\n+++ b/src/helpers.py\n@@ -0,0 +1,2 @@\n+def build_helper() -> str:\n+    return \"ok\"\n"
            ),
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert payload["patch_diff"]["plan_consistent"] is True
    assert payload["patch_diff"]["plan_missing_targets"] == []


def test_plan_consistency_test_only_no_false_positive(monkeypatch, tmp_path: Path) -> None:
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
    assert payload["patch_diff"]["plan_consistent"] is True
    assert payload["patch_diff"]["plan_missing_targets"] == []


def test_hard_invalid_regeneration_succeeds_once(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}
    captured_second_plan: dict[str, object] = {}

    def _provider(**kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+def broken(:\n",
                "error": None,
            }
        captured_second_plan.update(kwargs.get("patch_plan", {}))
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 2
    assert payload["patch_diff"]["status"] == "generated"
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["regenerated"] is True
    assert payload["patch_diff"]["regeneration"]["attempt"] == 1
    constraints = captured_second_plan.get("regeneration_constraints", [])
    assert isinstance(constraints, list)
    assert any("Limit additions to 300 lines." in str(item) for item in constraints)


def test_mixed_task_regeneration_allowed_targets_include_both_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}
    captured_second_plan: dict[str, object] = {}

    def _provider(**kwargs: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": "diff --git a/src/helpers.py b/src/helpers.py\n--- /dev/null\n+++ b/src/helpers.py\n@@ -0,0 +1,2 @@\n+def broken(:\n+    pass\n",
                "error": None,
            }
        captured_second_plan.update(kwargs.get("patch_plan", {}))
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": (
                "diff --git a/src/helpers.py b/src/helpers.py\n--- /dev/null\n+++ b/src/helpers.py\n@@ -0,0 +1,2 @@\n+def slugify(text):\n+    return text\n"
                "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n--- /dev/null\n+++ b/tests/test_helpers.py\n@@ -0,0 +1,2 @@\n+def test_slugify():\n+    assert True\n"
            ),
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(task="add a helpers module with a slugify(text) function and tests for it", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert calls["count"] == 2
    assert payload["patch_diff"]["regeneration_attempted"] is True
    allowed_targets = captured_second_plan.get("allowed_targets", [])
    assert sorted(allowed_targets) == ["src/helpers.py", "tests/test_helpers.py"]


def test_hard_invalid_regeneration_fails_still_invalid_and_once(monkeypatch, tmp_path: Path) -> None:
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
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+def broken(:\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    assert calls["count"] == 2
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] in {"syntactic_invalid", "hunk_count_mismatch"}
    assert payload["patch_diff"]["regeneration_attempted"] is True
    assert payload["patch_diff"]["regenerated"] is False
    assert payload["patch_diff"]["regeneration"]["attempt"] == 1


def test_provider_heartbeat_initial_generation_delay(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.runtime._PROVIDER_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    progress: list[str] = []

    def _provider(**_: object) -> dict[str, object]:
        time.sleep(0.03)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, progress_callback=lambda m: progress.append(str(m))),
        cwd=tmp_path,
        client=_Client(),
    )
    waiting = [m for m in progress if "waiting on provider for patch generation" in m]
    assert waiting
    assert progress[-1] != waiting[-1]


def test_provider_heartbeat_regeneration_delay(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.runtime._PROVIDER_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    progress: list[str] = []
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "not a diff", "error": None}
        time.sleep(0.03)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/tests/test_example.py b/tests/test_example.py\n--- a/tests/test_example.py\n+++ b/tests/test_example.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    build_run_payload(
        options=TaskOptions(task="fix tests", propose_patch=True, progress_callback=lambda m: progress.append(str(m))),
        cwd=tmp_path,
        client=_Client(),
    )
    assert any("waiting on provider for regeneration" in m for m in progress)


def test_provider_heartbeat_post_invalid_regeneration_delay(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.runtime._PROVIDER_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    progress: list[str] = []
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+def broken(:\n",
                "error": None,
            }
        time.sleep(0.03)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, progress_callback=lambda m: progress.append(str(m))),
        cwd=tmp_path,
        client=_Client(),
    )
    assert any("waiting on provider for post-invalid regeneration" in m for m in progress)


def test_provider_heartbeat_quiet_suppressed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.runtime._PROVIDER_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    progress: list[str] = []

    def _provider(**_: object) -> dict[str, object]:
        time.sleep(0.03)
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, progress_callback=lambda _m: None),
        cwd=tmp_path,
        client=_Client(),
    )
    assert progress == []


def test_invalid_reason_fields_syntax_then_excessive_size(monkeypatch, tmp_path: Path) -> None:
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
                "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+def broken(:\n",
                "error": None,
            }
        big_lines = "".join(f"+line_{i}\n" for i in range(301))
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": f"diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,302 @@\n-a\n+b\n{big_lines}",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    pd = payload["patch_diff"]
    assert pd["status"] == "invalid"
    assert pd["initial_invalid_reason"] == "syntactic_invalid"
    assert pd["regeneration_trigger_reason"] == "syntactic_invalid"
    assert pd["final_invalid_reason"] == "excessive_diff_size"
    assert pd["error"] == "excessive_diff_size"
    assert pd["regeneration"]["regenerated_invalid_reason"] == "excessive_diff_size"


def test_invalid_reason_fields_excessive_then_plan_inconsistent(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    calls = {"count": 0}

    def _provider(**_: object) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            big_lines = "".join(f"+line_{i}\n" for i in range(801))
            return {
                "available": True,
                "provider": "openai",
                "model": "gpt-4.1-mini",
                "diff": f"diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,802 @@\n-a\n+b\n{big_lines}",
                "error": None,
            }
        return {
            "available": True,
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+from src.helpers import util\n",
            "error": None,
        }

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    pd = payload["patch_diff"]
    assert pd["status"] == "invalid"
    assert pd["initial_invalid_reason"] == "excessive_diff_size"
    assert pd["regeneration_trigger_reason"] == "excessive_diff_size"
    assert pd["final_invalid_reason"] == "plan_inconsistent"
    assert pd["error"] == "plan_inconsistent"
    assert pd["regeneration"]["regenerated_invalid_reason"] == "plan_inconsistent"


def test_invalid_reason_fields_no_regeneration(monkeypatch, tmp_path: Path) -> None:
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
            "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1 @@\n-a\n+b\n",
            "error": None,
        },
    )
    payload = build_run_payload(options=TaskOptions(task="add feature", propose_patch=True), cwd=tmp_path, client=_Client())
    pd = payload["patch_diff"]
    assert pd["status"] == "generated"
    assert pd["initial_invalid_reason"] is None
    assert pd["regeneration_trigger_reason"] is None
    assert pd["final_invalid_reason"] is None


def test_provider_timeout_during_initial_generation(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _provider(**_: object) -> dict[str, object]:
        time.sleep(1.2)
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "x", "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, provider_timeout_seconds=1),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["status"] == "unavailable"
    assert payload["patch_diff"]["error"] == "provider_timeout"
    assert payload["patch_diff"]["path"] is None
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_provider_timeout_during_regeneration_sets_timeout_result(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("aegis_code.runtime._PROVIDER_HEARTBEAT_SECONDS", 1)
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
                "diff": "diff --git a/src/main.py b/src/main.py\n--- a/src/main.py\n+++ b/src/main.py\n@@ -1 +1,2 @@\n-a\n+b\n+def broken(:\n",
                "error": None,
            }
        time.sleep(1.2)
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, provider_timeout_seconds=1),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["status"] == "invalid"
    assert payload["patch_diff"]["error"] == "provider_timeout"
    assert payload["patch_diff"]["regeneration"]["result"] == "timeout"
    assert payload["patch_diff"]["regeneration"]["regenerated_invalid_reason"] == "provider_timeout"
    assert payload["patch_diff"]["invalid_diff_path"] is not None
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()


def test_provider_timeout_uses_configurable_value(monkeypatch, tmp_path: Path) -> None:
    aegis_dir = tmp_path / ".aegis"
    aegis_dir.mkdir(parents=True, exist_ok=True)
    (aegis_dir / "aegis-code.yml").write_text("providers:\n  enabled: true\n  timeout_seconds: 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})

    def _provider(**_: object) -> dict[str, object]:
        time.sleep(1.2)
        return {"available": True, "provider": "openai", "model": "gpt-4.1-mini", "diff": "x", "error": None}

    monkeypatch.setattr("aegis_code.runtime.generate_patch_diff", _provider)
    payload = build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["error"] == "provider_timeout"


def test_provider_timeout_cli_override_is_used_by_provider_calls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "aegis_code.runtime.run_configured_tests",
        lambda _cmd, cwd=None: command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    )
    monkeypatch.setattr("aegis_code.runtime.analyze_failures_sll", lambda _text: {"available": False})
    captured: dict[str, int] = {}

    def _hb(options: object, label: str, fn: object, timeout_seconds: int):
        captured[label] = int(timeout_seconds)
        return {"available": False, "provider": "openai", "model": "gpt-4.1-mini", "diff": "", "error": "provider_timeout"}, True

    monkeypatch.setattr("aegis_code.runtime._run_with_provider_heartbeat", _hb)
    payload = build_run_payload(
        options=TaskOptions(task="add feature", propose_patch=True, provider_timeout_seconds=30),
        cwd=tmp_path,
        client=_Client(),
    )
    assert payload["patch_diff"]["error"] == "provider_timeout"
    assert captured.get("patch generation") == 30
