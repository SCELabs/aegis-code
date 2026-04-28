from __future__ import annotations

from pathlib import Path

from aegis_code.context.failure_context import build_failure_context


def test_build_failure_context_reads_only_targeted_files(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    pkg_dir = tmp_path / "aegis_code"
    tests_dir.mkdir()
    pkg_dir.mkdir()

    failing_test = tests_dir / "test_report.py"
    source_file = pkg_dir / "report.py"
    unrelated = pkg_dir / "runtime.py"

    failing_test.write_text("def test_x():\n    assert False\n", encoding="utf-8")
    source_file.write_text("def render():\n    return 'ok'\n", encoding="utf-8")
    unrelated.write_text("def run():\n    return 1\n", encoding="utf-8")

    failures = [
        {
            "test_name": "tests/test_report.py::test_x",
            "file": "tests/test_report.py",
            "error": "AssertionError",
            "line": 2,
        }
    ]

    context = build_failure_context(failures, tmp_path)
    paths = [item["path"] for item in context["files"]]

    assert "tests\\test_report.py" in paths
    assert "aegis_code\\report.py" in paths
    assert "aegis_code\\runtime.py" not in paths
    assert len(paths) == 2

