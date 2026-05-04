from __future__ import annotations

import sys
import types

from aegis_code.providers import generate_patch_diff
from aegis_code.providers.openai_compatible import generate_patch_diff_openai_compatible


def _provider_kwargs() -> dict[str, object]:
    return {
        "provider": "openai-compatible",
        "model": "openai:gpt-4.1-mini",
        "task": "fix",
        "failures": {"failure_count": 1, "failed_tests": [{"test_name": "x", "file": "tests/test_x.py"}]},
        "context": {"files": [{"path": "tests/test_x.py", "content": "x"}]},
        "patch_plan": {"proposed_changes": [{"file": "x"}]},
        "aegis_execution": {},
        "api_key_env": "OPENAI_API_KEY",
        "base_url": "http://localhost:11434/v1",
        "max_context_chars": 1000,
    }


def test_openai_compatible_routes_correctly(monkeypatch) -> None:
    called = {"ok": False}

    def _fake(**kwargs: object) -> dict[str, object]:
        called["ok"] = True
        assert kwargs.get("base_url") == "http://localhost:11434/v1"
        return {"available": True, "provider": "openai-compatible", "model": "gpt-4.1-mini", "diff": "diff --git a/x b/x\n", "error": None}

    monkeypatch.setattr("aegis_code.providers.generate_patch_diff_openai_compatible", _fake)
    result = generate_patch_diff(**_provider_kwargs())
    assert called["ok"] is True
    assert result["provider"] == "openai-compatible"


def test_openai_compatible_missing_base_url_fails() -> None:
    kwargs = _provider_kwargs()
    kwargs["base_url"] = ""
    result = generate_patch_diff_openai_compatible(**kwargs)
    assert result["available"] is False
    assert "base_url" in str(result["error"]).lower()


def test_openai_compatible_missing_api_key_does_not_fail(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fake_openai = types.ModuleType("openai")
    captured: dict[str, str] = {}

    class _Message:
        content = "diff --git a/tests/test_x.py b/tests/test_x.py\n--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1 +1 @@\n-a\n+b\n"

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
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = _Chat()

    fake_openai.OpenAI = _ClientImpl  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    result = generate_patch_diff_openai_compatible(**_provider_kwargs())
    assert result["available"] is True
    assert captured["api_key"] == "dummy"
    assert captured["base_url"] == "http://localhost:11434/v1"


def test_openai_compatible_diff_validation_enforced(monkeypatch) -> None:
    fake_openai = types.ModuleType("openai")

    class _Message:
        content = "not a diff"

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
    result = generate_patch_diff_openai_compatible(**_provider_kwargs())
    assert result["available"] is False
    assert "unified diff" in str(result["error"]).lower()
