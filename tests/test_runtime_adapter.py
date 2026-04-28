from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from aegis_code.config import project_paths
from aegis_code.runtime import TaskOptions
from aegis_code.runtime_adapter import execute_task


def _fake_local_payload(options: TaskOptions, cwd: Path | None = None) -> dict[str, object]:
    return {
        "status": "ok",
        "task": options.task,
        "mode": options.mode or "balanced",
        "dry_run": options.dry_run,
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


def test_execute_task_uses_local_when_enhanced_disabled(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
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

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
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


def test_execute_task_uses_aegis_step_when_enabled_and_available(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False, "step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        called["local"] = True
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **kwargs: object) -> dict[str, object]:
            called["step"] = True
            assert kwargs["step_name"] == "aegis-code-runtime"
            assert kwargs["step_input"]["task"] == "x"
            assert kwargs["metadata"]["project_context"] == {"available": True}
            assert kwargs["metadata"]["budget_state"] == {"available": False}
            assert kwargs["metadata"]["runtime_policy"] == {"selected_mode": "balanced"}
            return {
                "actions": ["aegis-action"],
                "trace": ["aegis-trace"],
                "explanation": "guided",
                "metrics": {"calls": 1},
            }

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            assert base_url == "https://aegis-backend-production-4b47.up.railway.app"

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    result = execute_task(
        TaskOptions(
            task="x",
            project_context={"available": True},
            budget_state={"available": False},
            runtime_policy={"selected_mode": "balanced"},
        ),
        cwd=tmp_path,
    )
    assert called["local"] is True
    assert called["step"] is True
    assert result["adapter"]["mode"] == "aegis"
    assert result["adapter"]["aegis_client_available"] is True
    assert result["adapter"]["enhanced_enabled"] is True
    assert result["adapter"]["fallback_reason"] is None
    assert "aegis_result" in result
    assert result["actions"] == ["aegis-action"]
    assert result["trace"] == ["aegis-trace"]
    assert result["explanation"] == "guided"
    assert result["metrics"] == {"calls": 1}
    assert result["output"] == "local-output"


def test_execute_task_partial_step_result_keeps_local_structure(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"trace": ["remote-trace"]}

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
    assert result["trace"] == ["remote-trace"]
    assert result["final_answer"] == "local-answer"
    assert result["actions"] == ["local-action"]
    assert result["metrics"] == {"local": True}


def test_execute_task_falls_back_on_client_error_with_error_fields(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        called["local"] = True
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            raise RuntimeError("boom " + ("x" * 400))

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
    assert called["local"] is True
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["fallback_reason"] == "client_error"
    assert result["adapter"]["error_type"] == "RuntimeError"
    assert isinstance(result["adapter"]["error_message"], str)
    assert len(result["adapter"]["error_message"]) <= 300


def test_execute_task_success_persists_adapter_metadata_to_reports(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        return _fake_local_payload(options, cwd)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
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

    paths = project_paths(tmp_path)
    latest_json = json.loads(paths["latest_json"].read_text(encoding="utf-8"))
    latest_md = paths["latest_md"].read_text(encoding="utf-8")

    assert latest_json["adapter"]["mode"] == "aegis"
    assert latest_json["adapter"]["aegis_client_available"] is True
    assert latest_json["adapter"]["fallback_reason"] is None
    assert latest_json["adapter"]["fallback_reason"] != "import_missing"
    assert "## Runtime Adapter" in latest_md
    assert "Mode: `aegis`" in latest_md
    assert "Aegis client available: `True`" in latest_md
    assert "Fallback reason: `None`" in latest_md


def test_execute_task_fallback_persists_local_adapter_metadata_to_reports(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  enhanced_runtime: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))

    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["fallback_reason"] == "import_missing"

    paths = project_paths(tmp_path)
    latest_json = json.loads(paths["latest_json"].read_text(encoding="utf-8"))
    latest_md = paths["latest_md"].read_text(encoding="utf-8")

    assert latest_json["adapter"]["mode"] == "local"
    assert latest_json["adapter"]["aegis_client_available"] is False
    assert latest_json["adapter"]["fallback_reason"] == "import_missing"
    assert "Mode: `local`" in latest_md
    assert "Aegis client available: `False`" in latest_md
    assert "Fallback reason: `import_missing`" in latest_md
