from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task
from aegis_code.usage import get_usage_warning, load_usage


def _fake_local_payload(options: TaskOptions, cwd: Path | None = None) -> dict[str, object]:
    _ = cwd
    return {
        "status": "ok",
        "task": options.task,
        "mode": options.mode or "balanced",
        "dry_run": options.dry_run,
        "actions": ["local-action"],
    }


def test_usage_file_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", object)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(TaskOptions(task="x"), cwd=tmp_path)

    usage_path = tmp_path / ".aegis" / "usage.json"
    assert usage_path.exists()
    data = json.loads(usage_path.read_text(encoding="utf-8"))
    assert data["calls"] == 1


def test_usage_updates_on_run(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"actions": ["aegis-action"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(TaskOptions(task="x"), cwd=tmp_path)

    usage = load_usage(tmp_path)
    assert usage["calls"] == 1
    assert usage["successful"] == 1
    assert usage["fallbacks"] == 0


def test_usage_counts_actions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"actions": ["a1", "a2", "a3"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(TaskOptions(task="x"), cwd=tmp_path)

    usage = load_usage(tmp_path)
    assert usage["actions_applied"] == 3


def test_usage_fallback_tracking(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            raise RuntimeError("boom")

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(TaskOptions(task="x"), cwd=tmp_path)

    usage = load_usage(tmp_path)
    assert usage["calls"] == 1
    assert usage["successful"] == 0
    assert usage["fallbacks"] == 1


def test_usage_persists_across_runs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"actions": ["a1", "a2"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(TaskOptions(task="x"), cwd=tmp_path)
    execute_task(TaskOptions(task="y"), cwd=tmp_path)

    usage = load_usage(tmp_path)
    assert usage["calls"] == 2
    assert usage["successful"] == 2
    assert usage["fallbacks"] == 0
    assert usage["actions_applied"] == 4


def test_usage_warning_approaching() -> None:
    warning = get_usage_warning({"calls": 90})
    assert warning == {"type": "approaching_limit", "limit": 100}


def test_usage_warning_reached() -> None:
    warning = get_usage_warning({"calls": 100})
    assert warning == {"type": "limit_reached", "limit": 100}


def test_no_warning_below_threshold() -> None:
    warning = get_usage_warning({"calls": 89})
    assert warning is None
