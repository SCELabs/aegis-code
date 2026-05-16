from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from aegis_code.runtime_control_service import RuntimeControlService


def _cfg(*, control_enabled: object = True, enabled: bool = True, base_url: str = "http://example.test") -> SimpleNamespace:
    return SimpleNamespace(
        aegis=SimpleNamespace(
            control_enabled=control_enabled,
            enabled=enabled,
            base_url=base_url,
            timeout_ms=2000,
            max_retries=1,
        )
    )


def test_service_initialization_sets_control_state(tmp_path: Path) -> None:
    service = RuntimeControlService(options=None, config=_cfg(control_enabled="auto"), cwd=tmp_path)
    assert isinstance(service.control_state, dict)
    assert service.control_state.get("mode") == "auto"


def test_step_guidance_delegates_to_aegis_step(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class _Auto:
        def step(self, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            return {"model_tier": "cheap", "max_retries": 1, "allow_escalation": False, "context_mode": "minimal"}

    class _Client:
        def __init__(self, *, base_url: str) -> None:
            assert base_url == "http://example.test"

        def auto(self) -> _Auto:
            return _Auto()

    service = RuntimeControlService(
        options=None,
        config=_cfg(control_enabled=True),
        cwd=tmp_path,
        aegis_client_cls=_Client,
    )
    result = service.get_step_guidance(task="x", payload={"mode": "balanced", "dry_run": True})
    assert result["status"] == "applied"
    assert result["guidance"]["model_tier"] == "cheap"
    assert captured.get("step_name") == "aegis-code-runtime"


def test_step_guidance_disabled_returns_disabled_state(tmp_path: Path) -> None:
    service = RuntimeControlService(options=None, config=_cfg(control_enabled=False), cwd=tmp_path)
    result = service.get_step_guidance(task="x")
    assert result["status"] == "disabled"
    assert result["reason"] == "disabled_by_config"
    assert result["response"] is None


def test_advisory_guidance_delegates_to_advisory_adapter(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_advisory(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"available": True, "actions": ["narrow"], "explanation": "ok", "used_fallback": False}

    service = RuntimeControlService(
        options=None,
        config=_cfg(control_enabled=True),
        cwd=tmp_path,
        advisory_fn=_fake_advisory,
    )
    result = service.get_advisory_guidance(task="x", payload={"context": {"aegis": {"enabled": True}}})
    assert result["available"] is True
    assert captured.get("task") == "x"


def test_context_refinement_returns_local_context_when_control_disabled(tmp_path: Path) -> None:
    local = {"files": [{"path": "x.py", "content": "print('x')"}]}
    service = RuntimeControlService(options=None, config=_cfg(control_enabled=False), cwd=tmp_path)
    refined = service.get_context_refinement(task="x", context_text=local)
    assert refined == local


def test_corrective_control_handles_client_error_gracefully(tmp_path: Path) -> None:
    class _BrokenClient:
        def __init__(self, **_: object) -> None:
            raise RuntimeError("boom")

    service = RuntimeControlService(options=None, config=_cfg(control_enabled=True), cwd=tmp_path, aegis_client_cls=_BrokenClient)
    result = service.get_corrective_control(task="x", payload={"task_type": "general"})
    assert result["status"] == "client_error"
    assert "boom" in str(result["error"])
