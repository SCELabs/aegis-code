from __future__ import annotations

from types import SimpleNamespace

from aegis_code.runtime_control_policy import control_requested, resolve_control_state


def _cfg(control_enabled: object) -> SimpleNamespace:
    return SimpleNamespace(aegis=SimpleNamespace(control_enabled=control_enabled))


def test_control_state_enabled_by_config() -> None:
    state = resolve_control_state(options=None, config=_cfg(True), environment={"key_available": False})
    assert state["enabled"] is True
    assert state["requested"] is True
    assert state["reason"] == "enabled_by_config"
    assert state["mode"] == "enabled"


def test_control_state_disabled_by_config() -> None:
    state = resolve_control_state(options=None, config=_cfg(False), environment={"key_available": True})
    assert state["enabled"] is False
    assert state["requested"] is False
    assert state["reason"] == "disabled_by_config"
    assert state["mode"] == "disabled"


def test_control_state_auto_requires_key() -> None:
    disabled = resolve_control_state(options=None, config=_cfg("auto"), environment={"key_available": False})
    assert disabled["requested"] is False
    assert disabled["reason"] == "no_api_key"
    assert disabled["mode"] == "auto"

    enabled = resolve_control_state(options=None, config=_cfg("auto"), environment={"key_available": True})
    assert enabled["requested"] is True
    assert enabled["reason"] == "auto_enabled"
    assert enabled["mode"] == "auto"


def test_control_state_invalid_value_falls_back_without_auto_reason() -> None:
    state = resolve_control_state(options=None, config=_cfg("maybe"), environment={"key_available": False})
    assert state["requested"] is False
    assert state["reason"] == "disabled_by_config"
    assert state["mode"] == "auto"


def test_control_state_option_override_wins_over_config() -> None:
    options = SimpleNamespace(control_enabled=False)
    state = resolve_control_state(options=options, config=_cfg(True), environment={"key_available": True})
    assert state["requested"] is False
    assert state["reason"] == "disabled_by_option"
    assert state["source"] == "option"

    options = SimpleNamespace(control_enabled=True)
    state = resolve_control_state(options=options, config=_cfg(False), environment={"key_available": False})
    assert state["requested"] is True
    assert state["reason"] == "enabled_by_option"
    assert state["source"] == "option"


def test_control_requested_returns_boolean() -> None:
    assert control_requested(options=None, config=_cfg(True), environment={"key_available": False}) is True
    assert control_requested(options=None, config=_cfg("auto"), environment={"key_available": False}) is False
