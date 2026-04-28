from __future__ import annotations

from aegis_code.planning.patch_generator import generate_patch_plan


def test_generate_patch_plan_empty_failures() -> None:
    plan = generate_patch_plan(
        task="stabilize",
        failures=[],
        context={"files": []},
        aegis_decision={"context_mode": "focused"},
        sll_analysis={"available": False},
    )
    assert plan["proposed_changes"] == []
    assert plan["confidence"] == 0.95


def test_generate_patch_plan_includes_reason_and_confidence() -> None:
    plan = generate_patch_plan(
        task="fix tests",
        failures=[
            {
                "test_name": "tests/test_budget.py::test_remaining_budget_math",
                "file": "tests/test_budget.py",
                "error": "AssertionError: assert 1 == 2",
                "line": 8,
            }
        ],
        context={"files": [{"path": "aegis_code/budget.py", "content": "x"}]},
        aegis_decision={"context_mode": "focused"},
        sll_analysis={
            "available": True,
            "regime": "stable",
            "collapse_risk": 0.1,
            "fragmentation_risk": 0.2,
            "drift_risk": 0.1,
            "stable_random_risk": 0.1,
        },
    )

    assert plan["strategy"]
    assert isinstance(plan["confidence"], float)
    assert 0.0 <= plan["confidence"] <= 1.0
    assert len(plan["proposed_changes"]) == 1
    change = plan["proposed_changes"][0]
    assert change["file"] == "aegis_code/budget.py"
    assert change["change_type"] == "modify"
    assert "test_remaining_budget_math" in change["description"]
    assert "AssertionError" in change["reason"]


def test_generate_patch_plan_references_failing_file_when_context_missing() -> None:
    plan = generate_patch_plan(
        task="fix tests",
        failures=[
            {
                "test_name": "tests/test_alpha.py::test_alpha",
                "file": "tests/test_alpha.py",
                "error": "AssertionError: alpha",
                "line": 4,
            }
        ],
        context={"files": []},
        aegis_decision={"context_mode": "focused"},
        sll_analysis={"available": False},
    )
    assert len(plan["proposed_changes"]) == 1
    assert plan["proposed_changes"][0]["file"] == "tests/test_alpha.py"
