from __future__ import annotations

import os
import sys
import types
from pathlib import Path

from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task
from aegis_code.secrets import set_key


def _fake_local_payload(task: str) -> dict[str, object]:
    return {
        "status": "ok",
        "task": task,
        "mode": "balanced",
        "dry_run": False,
        "symptoms": ["unstable_workflow"],
        "verification": {"available": True},
        "failures": {"failure_count": 0},
        "output": "local-output",
        "final_answer": "local-answer",
        "metrics": {"local": True},
        "actions": ["local-action"],
        "trace": ["local-trace"],
        "explanation": "local-explanation",
    }


def test_aegis_key_from_secrets_used(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")
    set_key("AEGIS_API_KEY", "from_secrets", cwd=tmp_path)
    monkeypatch.delenv("AEGIS_API_KEY", raising=False)

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = cwd, client, write_report
        return _fake_local_payload(options.task)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            assert os.environ.get("AEGIS_API_KEY") == "from_secrets"
            return {"actions": ["guided"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert result["adapter"]["mode"] == "aegis"


def test_env_priority_over_secrets(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")
    set_key("AEGIS_API_KEY", "from_secrets", cwd=tmp_path)
    monkeypatch.setenv("AEGIS_API_KEY", "from_env")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = cwd, client, write_report
        return _fake_local_payload(options.task)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            assert os.environ.get("AEGIS_API_KEY") == "from_env"
            return {"actions": ["guided"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert result["adapter"]["mode"] == "aegis"


def test_no_key_behavior(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")
    monkeypatch.delenv("AEGIS_API_KEY", raising=False)

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = cwd, client, write_report
        return _fake_local_payload(options.task)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            if not os.environ.get("AEGIS_API_KEY"):
                raise RuntimeError("Missing Authorization header")
            return {"actions": ["guided"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["fallback_reason"] == "client_error"
