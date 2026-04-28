from __future__ import annotations

from aegis_code.models import CommandResult


def pytest_output_pass() -> str:
    return "============================== 3 passed in 0.02s =============================="


def pytest_output_fail() -> str:
    return "\n".join(
        [
            "=================================== FAILURES ===================================",
            "___________________________ test_example_failure ___________________________",
            "",
            "    def test_example_failure():",
            ">       assert 1 == 2",
            "E       AssertionError: assert 1 == 2",
            "",
            "tests/test_example.py:12: AssertionError",
            "=========================== short test summary info ===========================",
            "FAILED tests/test_example.py::test_example_failure - AssertionError: assert 1 == 2",
            "============================== 1 failed in 0.04s ==============================",
        ]
    )


def pytest_output_malformed() -> str:
    return "?? broken pytest output >> FAILED maybe::not-a-nodeid"


def command_result_from_output(
    output: str,
    *,
    status: str,
    exit_code: int | None,
    command: str = "pytest -q",
) -> CommandResult:
    return CommandResult(
        name="test",
        command=command,
        status=status,
        exit_code=exit_code,
        stdout=output if status == "ok" else "",
        stderr="" if status == "ok" else output,
        output_preview=output[:1200],
        full_output=output,
    )


def retry_sequence_fail_then_pass() -> list[CommandResult]:
    return [
        command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
        command_result_from_output(pytest_output_pass(), status="ok", exit_code=0),
    ]


def retry_sequence_fail_then_fail() -> list[CommandResult]:
    return [
        command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
        command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
        command_result_from_output(pytest_output_fail(), status="failed", exit_code=1),
    ]

