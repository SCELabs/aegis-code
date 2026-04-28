from __future__ import annotations

from aegis_code.execution_loop import synthesize_symptoms


def test_synthesize_symptoms_maps_failure_and_sll_and_dedupes() -> None:
    symptoms = synthesize_symptoms(
        failures={
            "failure_count": 1,
            "failed_tests": [
                {"test_name": "tests/test_x.py::test_x", "file": "", "error": "boom", "line": None}
            ],
        },
        sll_analysis={
            "available": True,
            "fragmentation_risk": 0.8,
            "collapse_risk": 0.7,
            "drift_risk": 0.9,
            "stable_random_risk": 0.95,
        },
        base_symptoms=["unstable_workflow", "test_failure"],
    )

    assert symptoms == [
        "unstable_workflow",
        "test_failure",
        "incomplete_failure_signal",
        "fragmented_output",
        "degenerate_loop",
        "ungrounded_output",
    ]


def test_synthesize_symptoms_without_sll_is_safe() -> None:
    symptoms = synthesize_symptoms(
        failures={"failure_count": 1, "failed_tests": [{"test_name": "x", "file": "tests/test_x.py"}]},
        sll_analysis={"available": False},
        base_symptoms=["base"],
    )
    assert symptoms == ["base", "test_failure"]
