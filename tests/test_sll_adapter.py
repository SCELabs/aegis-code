from __future__ import annotations

import sys
import types

from aegis_code.sll_adapter import (
    analyze_failures_sll,
    check_sll_available,
    classify_sll_risk,
    run_sll_analysis,
)


def test_check_sll_available_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "aegis_code.sll_adapter.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'structural_language_lab'")),
    )
    result = check_sll_available()
    assert result["available"] is False
    assert result["import_path"] == "structural_language_lab"
    assert result["error"]


def test_check_sll_available_available(monkeypatch) -> None:
    fake_module = types.ModuleType("structural_language_lab")
    fake_module.analyze_sequence = lambda _text: {"regime": "ok"}  # type: ignore[attr-defined]
    monkeypatch.setattr("aegis_code.sll_adapter.importlib.import_module", lambda _name: fake_module)
    result = check_sll_available()
    assert result["available"] is True
    assert result["import_path"] == "structural_language_lab"
    assert result["error"] is None


def test_analyze_failures_sll_unavailable_returns_flag(monkeypatch) -> None:
    fake_module = types.ModuleType("structural_language_lab")
    monkeypatch.setitem(sys.modules, "structural_language_lab", fake_module)

    result = analyze_failures_sll("failure text")

    assert result == {"available": False}


def test_analyze_failures_sll_normalizes_payload(monkeypatch) -> None:
    fake_module = types.ModuleType("structural_language_lab")

    def _analyze_sequence(_text: str) -> dict[str, object]:
        return {
            "regime": "chaotic",
            "collapse_risk": "0.7",
            "fragmentation_risk": 0.4,
            "drift_risk": 0.2,
            "stable_random_risk": 0.9,
        }

    fake_module.analyze_sequence = _analyze_sequence  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "structural_language_lab", fake_module)

    result = analyze_failures_sll("failure text")

    assert result == {
        "available": True,
        "regime": "chaotic",
        "collapse_risk": 0.7,
        "fragmentation_risk": 0.4,
        "drift_risk": 0.2,
        "stable_random_risk": 0.9,
    }


def test_run_sll_analysis_unavailable_when_import_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "aegis_code.sll_adapter.importlib.import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("No module named 'structural_language_lab'")),
    )
    result = run_sll_analysis("hello")
    assert result == {"available": False}


def test_run_sll_analysis_available_structured(monkeypatch) -> None:
    fake_module = types.ModuleType("structural_language_lab")

    def _analyze_sequence(_text: str) -> dict[str, object]:
        return {
            "regime": "boundary",
            "coherence": "0.8",
            "collapse_risk": 0.2,
            "fragmentation_risk": 0.6,
            "drift_risk": 0.3,
            "recommendation": "watch boundary drift",
        }

    fake_module.analyze_sequence = _analyze_sequence  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "structural_language_lab", fake_module)
    result = run_sll_analysis("some text")
    assert result == {
        "available": True,
        "regime": "boundary",
        "coherence": 0.8,
        "collapse_risk": 0.2,
        "fragmentation_risk": 0.6,
        "drift_risk": 0.3,
        "recommendation": "watch boundary drift",
    }


def test_classify_sll_risk_logic() -> None:
    assert classify_sll_risk({"available": True, "collapse_risk": 0.8}) == "high"
    assert classify_sll_risk({"available": True, "fragmentation_risk": 0.5}) == "watch"
    assert classify_sll_risk({"available": True, "drift_risk": 0.1}) == "low"
