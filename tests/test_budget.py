from aegis_code.budget import BudgetState


def test_budget_remaining_math() -> None:
    state = BudgetState(total=2.5, spent=0.75)
    assert state.remaining == 1.75


def test_budget_remaining_clamped() -> None:
    state = BudgetState(total=1.0, spent=2.0)
    assert state.remaining == 0.0
