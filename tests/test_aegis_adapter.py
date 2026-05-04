from __future__ import annotations

import sys
import time
import types

from aegis_code.aegis_adapter import get_aegis_guidance


def test_aegis_adapter_disabled_returns_unavailable() -> None:
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": False}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=2000,
        max_retries=1,
    )
    assert payload == {"available": False}


def test_aegis_adapter_import_failure_returns_unavailable(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "aegis", None)
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": True}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=2000,
        max_retries=1,
    )
    assert payload == {"available": False}


def test_aegis_adapter_success_path_normalizes_output(monkeypatch) -> None:
    fake_aegis = types.ModuleType("aegis")

    class _Result:
        actions = ["narrow scope"]
        explanation = "Try a smaller patch."
        used_fallback = True

    class _Auto:
        def llm(self, **_: object) -> _Result:
            return _Result()

    class _Client:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self) -> _Auto:
            return _Auto()

    class _Config:
        def __init__(self, **_: object) -> None:
            pass

    setattr(fake_aegis, "AegisClient", _Client)
    setattr(fake_aegis, "AegisConfig", _Config)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": True}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=2000,
        max_retries=1,
    )
    assert payload["available"] is True
    assert payload["actions"] == ["narrow scope"]
    assert payload["explanation"] == "Try a smaller patch."
    assert payload["used_fallback"] is True


def test_aegis_adapter_timeout_respected(monkeypatch) -> None:
    fake_aegis = types.ModuleType("aegis")

    class _Auto:
        def llm(self, **_: object):
            time.sleep(0.05)
            return object()

    class _Client:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self) -> _Auto:
            return _Auto()

    class _Config:
        def __init__(self, **_: object) -> None:
            pass

    setattr(fake_aegis, "AegisClient", _Client)
    setattr(fake_aegis, "AegisConfig", _Config)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": True}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=5,
        max_retries=0,
    )
    assert payload["available"] is False
    assert "timeout" in str(payload.get("error", "")).lower()


def test_aegis_adapter_retries_bounded(monkeypatch) -> None:
    fake_aegis = types.ModuleType("aegis")
    calls = {"count": 0}

    class _Auto:
        def llm(self, **_: object):
            calls["count"] += 1
            raise RuntimeError("boom")

    class _Client:
        def __init__(self, **_: object) -> None:
            pass

        def auto(self) -> _Auto:
            return _Auto()

    class _Config:
        def __init__(self, **_: object) -> None:
            pass

    setattr(fake_aegis, "AegisClient", _Client)
    setattr(fake_aegis, "AegisConfig", _Config)
    monkeypatch.setitem(sys.modules, "aegis", fake_aegis)
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": True}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=2000,
        max_retries=2,
    )
    assert payload["available"] is False
    assert calls["count"] == 3


def test_aegis_adapter_no_exceptions_escape(monkeypatch) -> None:
    monkeypatch.setattr("aegis_code.aegis_adapter._call_with_timeout", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad wrapper")))
    payload = get_aegis_guidance(
        task="fix failing tests",
        context={"aegis": {"enabled": True}},
        failures={"failure_count": 1},
        runtime_policy={"selected_mode": "balanced"},
        timeout_ms=2000,
        max_retries=1,
    )
    assert payload["available"] is False
    assert "bad wrapper" in str(payload.get("error", ""))
