from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.providers.openai_provider import generate_patch_diff_openai
from aegis_code.report import render_markdown_report
from aegis_code.runtime import TaskOptions, build_run_payload, run_task
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
