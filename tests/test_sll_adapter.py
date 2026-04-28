from __future__ import annotations

import types
import sys

from aegis_code.sll_adapter import analyze_failures_sll


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
