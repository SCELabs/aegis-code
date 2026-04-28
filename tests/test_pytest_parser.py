from __future__ import annotations

from aegis_code.parsers.pytest_parser import parse_pytest_output
from tests.helpers import pytest_output_fail, pytest_output_malformed


def test_parse_pytest_output_extracts_failures() -> None:
    output = pytest_output_fail().replace("tests/test_example.py", "tests/test_budget.py").replace(
        "test_example_failure", "test_remaining_budget_math"
    ).replace(":12:", ":8:")

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
    assert failure["line"] == 22


def test_parse_pytest_output_short_summary_only() -> None:
    output = """
=========================== short test summary info ===========================
FAILED tests/test_alpha.py::test_a - AssertionError: alpha
FAILED tests/test_beta.py::test_b - ValueError: beta
""".strip()
    parsed = parse_pytest_output(output)
    assert parsed["failure_count"] == 2
    assert parsed["failed_tests"][0]["file"] == "tests/test_alpha.py"
    assert parsed["failed_tests"][1]["file"] == "tests/test_beta.py"


def test_parse_pytest_output_multiline_e_lines() -> None:
    output = """
FAILED tests/test_gamma.py::test_g
E   AssertionError: first line
E   second line
""".strip()
    parsed = parse_pytest_output(output)
    assert parsed["failure_count"] == 1
    assert "first line" in parsed["failed_tests"][0]["error"]


def test_parse_pytest_output_malformed_is_safe() -> None:
    parsed = parse_pytest_output(pytest_output_malformed())
    assert isinstance(parsed, dict)
    assert "failed_tests" in parsed
    assert "failure_count" in parsed
