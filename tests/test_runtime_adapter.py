from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task


def _fake_local_payload(options: TaskOptions, cwd: Path | None = None) -> dict[str, object]:
    return {
        "status": "ok",
        "task": options.task,
        "mode": options.mode or "balanced",
        "dry_run": options.dry_run,
    }


def test_execute_task_uses_local_when_enhanced_disabled(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["enhanced_enabled"] is False
    assert result["adapter"]["fallback_reason"] == "disabled"


def test_execute_task_falls_back_when_enhanced_enabled_but_import_missing(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["aegis_client_available"] is False
    assert result["adapter"]["enhanced_enabled"] is True
    assert result["adapter"]["fallback_reason"] == "import_missing"


def test_execute_task_uses_aegis_when_enabled_and_available(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False, "llm": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def llm(self, **kwargs: object) -> dict[str, object]:
            called["llm"] = True
            assert kwargs["prompt"] == "x"
            return {"final_answer": "done", "metrics": {"tokens": 1}}

    class _FakeClient:
        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert called["llm"] is True
    assert result["adapter"]["mode"] == "aegis"
    assert result["adapter"]["aegis_client_available"] is True
    assert result["adapter"]["enhanced_enabled"] is True
    assert result["adapter"]["fallback_reason"] is None
    assert "final_answer" in result
    assert "metrics" in result
    assert "actions" in result
    assert "trace" in result
    assert "explanation" in result


def test_execute_task_falls_back_on_client_error(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def llm(self, **_: object) -> dict[str, object]:
            raise RuntimeError("boom")

    class _FakeClient:
        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["aegis_client_available"] is True
    assert result["adapter"]["enhanced_enabled"] is True
    assert result["adapter"]["fallback_reason"] == "client_error"
