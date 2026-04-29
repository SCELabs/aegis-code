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


def test_execute_task_uses_local_when_no_aegis_key_in_auto_mode(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}
    monkeypatch.delenv("AEGIS_API_KEY", raising=False)

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = write_report
        called["local"] = True
        return _fake_local_payload(options, cwd)

    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)
    monkeypatch.setitem(sys.modules, "aegis", types.ModuleType("aegis"))
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["local"] is True
    assert result["adapter"]["mode"] == "local"
    assert result["adapter"]["control_requested"] is False
    assert result["adapter"]["control_status"] == "disabled"
    assert result["adapter"]["control_reason"] == "no_api_key"


def test_execute_task_falls_back_when_control_requested_but_import_missing(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  control_enabled: true\n",
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
    assert result["adapter"]["control_requested"] is True
    assert result["adapter"]["fallback_reason"] == "import_missing"


def test_execute_task_auto_enables_control_when_key_present(monkeypatch, tmp_path: Path) -> None:
    called = {"step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "secrets.local.json").write_text('{"AEGIS_API_KEY":"x"}', encoding="utf-8")

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            called["step"] = True
            return {"actions": ["guided"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["step"] is True
    assert result["adapter"]["control_requested"] is True
    assert result["adapter"]["control_status"] == "enabled"


def test_execute_task_control_disabled_even_with_key(monkeypatch, tmp_path: Path) -> None:
    called = {"step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  control_enabled: false\n", encoding="utf-8")
    (tmp_path / ".aegis" / "secrets.local.json").write_text('{"AEGIS_API_KEY":"x"}', encoding="utf-8")

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            called["step"] = True
            return {}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["step"] is False
    assert result["adapter"]["control_requested"] is False
    assert result["adapter"]["control_reason"] == "disabled_by_config"


def test_execute_task_legacy_enhanced_runtime_false_disables_control(monkeypatch, tmp_path: Path) -> None:
    called = {"step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: false\n", encoding="utf-8")
    (tmp_path / ".aegis" / "secrets.local.json").write_text('{"AEGIS_API_KEY":"x"}', encoding="utf-8")

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            called["step"] = True
            return {}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["step"] is False
    assert result["adapter"]["control_requested"] is False


def test_execute_task_legacy_enhanced_runtime_true_enables_control(monkeypatch, tmp_path: Path) -> None:
    called = {"step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text("aegis:\n  enhanced_runtime: true\n", encoding="utf-8")

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            called["step"] = True
            return {"actions": ["guided"]}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    result = execute_task(TaskOptions(task="x"), cwd=tmp_path)
    assert called["step"] is True
    assert result["adapter"]["control_requested"] is True


def test_execute_task_uses_aegis_step_when_enabled_and_available(monkeypatch, tmp_path: Path) -> None:
    called = {"local": False, "step": False}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  control_enabled: true\n",
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
    assert result["adapter"]["control_requested"] is True
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
        "aegis:\n  control_enabled: true\n",
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
        "aegis:\n  control_enabled: true\n",
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
        "aegis:\n  control_enabled: true\n",
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
    assert "## Aegis Control" in latest_md
    assert "Status: `enabled`" in latest_md
    assert "Client available: `True`" in latest_md
    assert "Reason: `guidance_applied`" in latest_md


def test_execute_task_context_mode_minimal_reduces_context(monkeypatch, tmp_path: Path) -> None:
    seen_context = {"total_chars": None}
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  control_enabled: true\n",
        encoding="utf-8",
    )

    def _fake_local(*, options, cwd=None, client=None, write_report=True):
        _ = cwd, client, write_report
        seen_context["total_chars"] = (options.project_context or {}).get("total_chars")
        return _fake_local_payload(options)

    class _FakeFlow:
        def step(self, **_: object) -> dict[str, object]:
            return {"context_mode": "minimal"}

    class _FakeClient:
        def __init__(self, base_url: str) -> None:
            _ = base_url

        def auto(self) -> _FakeFlow:
            return _FakeFlow()

    fake_aegis = types.ModuleType("aegis")
    setattr(fake_aegis, "AegisClient", _FakeClient)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    monkeypatch.setattr("aegis_code.runtime._run_task_local", _fake_local)

    execute_task(
        TaskOptions(
            task="x",
            project_context={"available": True, "files": {"project_summary": "abcdef"}, "total_chars": 100},
        ),
        cwd=tmp_path,
    )
    assert seen_context["total_chars"] == 50


def test_execute_task_fallback_persists_local_adapter_metadata_to_reports(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".aegis").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".aegis" / "aegis-code.yml").write_text(
        "aegis:\n  control_enabled: true\n",
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
    assert "Status: `fallback`" in latest_md
    assert "Client available: `False`" in latest_md
    assert "Reason: `import_missing`" in latest_md
