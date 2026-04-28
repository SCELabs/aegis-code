from __future__ import annotations

from aegis_code.parsers.pytest_parser import parse_pytest_output


def test_parse_pytest_output_extracts_failures() -> None:
    output = """
============================= test session starts =============================
__________________________________ FAILURES ___________________________________
_________________________ test_remaining_budget_math __________________________

    def test_remaining_budget_math():
>       assert 1 == 2
E       assert 1 == 2

tests/test_budget.py:8: AssertionError
=========================== short test summary info ===========================
FAILED tests/test_budget.py::test_remaining_budget_math - AssertionError: assert 1 == 2
============================== 1 failed in 0.05s ==============================
""".strip()

    parsed = parse_pytest_output(output)

    assert parsed["failure_count"] == 1
    assert parsed["failed_tests"][0]["test_name"] == "tests/test_budget.py::test_remaining_budget_math"
    assert parsed["failed_tests"][0]["file"] == "tests/test_budget.py"
    assert parsed["failed_tests"][0]["error"]
    assert parsed["failed_tests"][0]["line"] == 8


def test_parse_pytest_output_handles_partial_output() -> None:
    output = "FAILED tests/test_cli.py::test_cli_dry_run_writes_report - AssertionError"
    parsed = parse_pytest_output(output)

    assert parsed["failure_count"] == 1
    assert parsed["failed_tests"][0]["file"] == "tests/test_cli.py"
    assert parsed["failed_tests"][0]["line"] is None


def test_parse_pytest_output_handles_multiline_error_from_summary_and_traceback() -> None:
    output = """
=========================== short test summary info ===========================
FAILED tests/test_report.py::test_report_generation_writes_json_and_md - AssertionError: section missing
Traceback (most recent call last):
  File "tests/test_report.py", line 22, in test_report_generation_writes_json_and_md
    assert "## Failures" in content
E   AssertionError: section missing
""".strip()
    parsed = parse_pytest_output(output)

    assert parsed["failure_count"] == 1
    failure = parsed["failed_tests"][0]
    assert failure["test_name"] == "tests/test_report.py::test_report_generation_writes_json_and_md"
    assert failure["file"] == "tests/test_report.py"
    assert "AssertionError" in failure["error"]
