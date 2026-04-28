from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.models import AegisDecision
from aegis_code.providers.openai_provider import generate_patch_diff_openai
from aegis_code.report import render_markdown_report
from aegis_code.runtime import TaskOptions, build_run_payload
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
            "diff": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-a\n+b\n",
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
    report = render_markdown_report(payload)
    assert "## Patch Diff Proposal" in report
    assert "Provider: `openai`" in report
    assert "Path: `" in report


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
    assert not (tmp_path / ".aegis" / "runs" / "latest.diff").exists()
