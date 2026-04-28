from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task


def test_execute_task_falls_back_when_aegis_missing(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return {"status": "ok", "task": options.task, "cwd": str(cwd) if cwd else None}

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    sys.modules.pop("aegis", None)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["status"] == "ok"


def test_execute_task_uses_local_even_when_aegis_present(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}

    def _fake_local(*, options, cwd=None, client=None):
        called["local"] = True
        return {"status": "ok", "task": options.task}

    fake_aegis = types.ModuleType("aegis")

    class _FakeClient:  # pragma: no cover - existence check only
        pass

    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["status"] == "ok"
