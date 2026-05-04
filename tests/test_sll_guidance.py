from __future__ import annotations

from aegis_code.sll_guidance import build_sll_fix_guidance


def test_fragmentation_high_maps_to_narrow_scope() -> None:
    result = build_sll_fix_guidance(
        {"available": True, "regime": "fragmentation", "collapse_risk": 0.2, "fragmentation_risk": 0.9, "drift_risk": 0.1}
    )
    assert result["strategy"] == "narrow_scope"


def test_collapse_high_maps_to_change_approach() -> None:
    result = build_sll_fix_guidance(
        {"available": True, "regime": "unity", "collapse_risk": 0.8, "fragmentation_risk": 0.1, "drift_risk": 0.1}
    )
    assert result["strategy"] == "change_approach"


def test_drift_maps_to_re_anchor() -> None:
    result = build_sll_fix_guidance(
        {"available": True, "regime": "unity", "collapse_risk": 0.1, "fragmentation_risk": 0.1, "drift_risk": 0.5}
    )
    assert result["strategy"] == "re_anchor"


def test_boundary_low_maps_to_proceed() -> None:
    result = build_sll_fix_guidance(
        {"available": True, "regime": "boundary", "collapse_risk": 0.1, "fragmentation_risk": 0.1, "drift_risk": 0.1}
    )
    assert result["strategy"] == "proceed"
