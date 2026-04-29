from __future__ import annotations

from aegis_code.patches.diff_evaluator import evaluate_diff


def _failures() -> dict:
    return {
        "failure_count": 1,
        "failed_tests": [
            {
                "test_name": "tests/test_budget.py::test_remaining_budget_math",
                "file": "tests/test_budget.py",
                "error": "AssertionError",
                "line": 8,
            }
        ],
    }


def _context() -> dict:
    return {
        "files": [
            {"path": "tests/test_budget.py", "content": "x"},
            {"path": "aegis_code/budget.py", "content": "x"},
        ]
    }


def test_evaluate_diff_valid_and_relevant() -> None:
    diff = "diff --git a/aegis_code/budget.py b/aegis_code/budget.py\n--- a/aegis_code/budget.py\n+++ b/aegis_code/budget.py\n@@ -1 +1 @@\n-a\n+b\n"
    result = evaluate_diff(diff, _failures(), _context())
    assert result["grounded"] is True
    assert result["relevant_files"] is True
    assert result["confidence"] >= 0.8
    assert not result["issues"]


def test_evaluate_diff_unknown_file_marks_no_targets() -> None:
    diff = "diff --git a/unknown.py b/unknown.py\n--- a/unknown.py\n+++ b/unknown.py\n@@ -1 +1 @@\n-a\n+b\n"
    result = evaluate_diff(diff, _failures(), _context())
    assert result["grounded"] is False
    assert "no_file_targets" in result["issues"]


def test_evaluate_diff_safe_new_file_is_not_rejected_as_unknown_target() -> None:
    diff = (
        "diff --git a/aegis_code/new_module.py b/aegis_code/new_module.py\n"
        "--- /dev/null\n"
        "+++ b/aegis_code/new_module.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n"
    )
    result = evaluate_diff(diff, _failures(), _context())
    assert result["grounded"] is True
    assert "no_file_targets" not in result["issues"]


def test_evaluate_diff_unrelated_file() -> None:
    context = {"files": [{"path": "docs/readme.md", "content": "x"}]}
    diff = "diff --git a/docs/readme.md b/docs/readme.md\n--- a/docs/readme.md\n+++ b/docs/readme.md\n@@ -1 +1 @@\n-a\n+b\n"
    result = evaluate_diff(diff, _failures(), context)
    assert result["relevant_files"] is True


def test_evaluate_diff_empty_diff() -> None:
    result = evaluate_diff("", _failures(), _context())
    assert result["grounded"] is False
    assert result["relevant_files"] is False
    assert result["confidence"] <= 0.3
    assert "empty_diff" in result["issues"]


def test_evaluate_diff_mixed_case_is_deterministic() -> None:
    diff = "--- a/aegis_code/budget.py\n+++ b/aegis_code/budget.py\n"
    result_a = evaluate_diff(diff, _failures(), _context())
    result_b = evaluate_diff(diff, _failures(), _context())
    assert result_a == result_b


def test_task_context_relevance() -> None:
    context = {"files": [{"path": "src/main.py", "content": "x"}]}
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = evaluate_diff(diff, {"failure_count": 0, "failed_tests": []}, context)
    assert result["relevant_files"] is True


def test_new_file_with_entrypoint_modification() -> None:
    context = {"files": [{"path": "main.py", "content": "x"}]}
    diff = (
        "diff --git a/main.py b/main.py\n"
        "--- a/main.py\n"
        "+++ b/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "diff --git a/src/helper.py b/src/helper.py\n"
        "--- /dev/null\n"
        "+++ b/src/helper.py\n"
        "@@ -0,0 +1 @@\n"
        "+x=1\n"
    )
    result = evaluate_diff(diff, {"failure_count": 0, "failed_tests": []}, context)
    assert result["relevant_files"] is True


def test_unrelated_file_still_flagged() -> None:
    context = {"files": [{"path": "src/main.py", "content": "x"}]}
    diff = (
        "diff --git a/docs/readme.md b/docs/readme.md\n"
        "--- a/docs/readme.md\n"
        "+++ b/docs/readme.md\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = evaluate_diff(diff, {"failure_count": 0, "failed_tests": []}, context)
    assert result["relevant_files"] is False
    assert "unrelated_files" in result["issues"]
