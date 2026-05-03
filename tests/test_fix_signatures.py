from __future__ import annotations

from aegis_code.fix.signatures import build_failure_signature
from aegis_code.models import CommandResult


def _result(output: str) -> CommandResult:
    return CommandResult(
        name="tests",
        command="pytest -q",
        status="failed",
        exit_code=1,
        stdout="",
        stderr="",
        output_preview="",
        full_output=output,
    )


def test_failure_signature_ignores_line_number_changes() -> None:
    out_a = (
        "=================================== FAILURES ===================================\n"
        "________ test_action ________\n"
        "tests/test_client.py:120: AssertionError: 'test_action' not found in []\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests/test_client.py::test_action - AssertionError: 'test_action' not found in []\n"
        "============================== 1 failed in 0.12s ==============================\n"
    )
    out_b = (
        "=================================== FAILURES ===================================\n"
        "________ test_action ________\n"
        "tests\\test_client.py:245: AssertionError: 'test_action' not found in []\n"
        "=========================== short test summary info ===========================\n"
        "FAILED tests\\test_client.py::test_action - AssertionError: 'test_action' not found in []\n"
        "============================== 1 failed in 1.32s ==============================\n"
    )
    assert build_failure_signature(_result(out_a)) == build_failure_signature(_result(out_b))


def test_failure_signature_distinguishes_different_failing_tests() -> None:
    out_a = (
        "=========================== short test summary info ===========================\n"
        "FAILED tests/test_client.py::test_action - AssertionError: x\n"
    )
    out_b = (
        "=========================== short test summary info ===========================\n"
        "FAILED tests/test_client.py::test_other_action - AssertionError: x\n"
    )
    assert build_failure_signature(_result(out_a)) != build_failure_signature(_result(out_b))

