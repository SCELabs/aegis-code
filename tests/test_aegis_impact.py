from __future__ import annotations

import sys
import types
from pathlib import Path

from aegis_code.config import project_paths
from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task


def _fake_local_payload(options: TaskOptions, cwd: Path | None = None) -> dict[str, object]:
    _ = cwd
    return {
        "status": "ok",
        "task": options.task,
        "mode": options.mode or "balanced",
        "dry_run": options.dry_run,
        "actions": ["local-action"],
        "trace": ["local-trace"],
        "explanation": "local-explanation",
    }


def test_aegis_impact_present_when_aegis_used(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"actions": ["aegis-action"], "model_tier": "cheap"}

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
    impact = result.get("aegis_impact", {})
    assert impact.get("used") is True
    assert impact.get("fallback_used") is False
    assert impact.get("override_applied") is True
    latest_json = project_paths(tmp_path)["latest_json"]
    assert latest_json.exists()
    assert "\"aegis_impact\"" in latest_json.read_text(encoding="utf-8")


def test_aegis_impact_zero_when_local_mode(monkeypatch, tmp_path: Path) -> None:
    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    impact = result.get("aegis_impact", {})
    assert impact.get("used") is False
    assert impact.get("action_count") == 1
    assert impact.get("override_applied") is False
    assert impact.get("fallback_used") is True


def test_aegis_impact_counts_actions(monkeypatch, tmp_path: Path) -> None:
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

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    impact = result.get("aegis_impact", {})
    assert impact.get("action_count") == 3


def test_aegis_impact_fallback_flag(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = client, write_report
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    impact = result.get("aegis_impact", {})
    assert impact.get("fallback_used") is True
    assert impact.get("used") is False
