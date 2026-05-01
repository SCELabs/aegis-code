from __future__ import annotations

from pathlib import Path

from aegis_code.patches.diff_inspector import inspect_diff


def test_inspect_diff_valid_single_file(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n", encoding="utf-8")
    diff = (
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-value = 1\n"
        "+value = 2\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert result["valid"] is True
    assert result["summary"]["file_count"] == 1
    assert result["summary"]["hunk_count"] == 1
    assert result["summary"]["additions"] == 1
    assert result["summary"]["deletions"] == 1
    assert result["files"][0]["exists"] is True


def test_inspect_diff_missing_file_warning(tmp_path: Path) -> None:
    diff = (
        "diff --git a/aegis_code/missing.py b/aegis_code/missing.py\n"
        "--- a/aegis_code/missing.py\n"
        "+++ b/aegis_code/missing.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert result["valid"] is True
    assert any("referenced file missing" in item for item in result["warnings"])


def test_inspect_diff_empty_is_invalid() -> None:
    result = inspect_diff("")
    assert result["valid"] is False
    assert "empty_diff" in result["errors"]


def test_inspect_diff_touches_aegis_warns(tmp_path: Path) -> None:
    diff = (
        "diff --git a/.aegis/runs/latest.diff b/.aegis/runs/latest.diff\n"
        "--- a/.aegis/runs/latest.diff\n"
        "+++ b/.aegis/runs/latest.diff\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert any("internal_or_generated_path" in item for item in result["warnings"])


def test_inspect_diff_normalizes_a_b_prefixes(tmp_path: Path) -> None:
    target = tmp_path / "foo.py"
    target.write_text("x=1\n", encoding="utf-8")
    diff = (
        "diff --git a/foo.py b/foo.py\n"
        "--- a/foo.py\n"
        "+++ b/foo.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert result["files"][0]["old_path"] == "foo.py"
    assert result["files"][0]["new_path"] == "foo.py"


def test_inspect_diff_warns_unsafe_absolute_path(tmp_path: Path) -> None:
    diff = (
        "diff --git a//absolute/foo.py b//absolute/foo.py\n"
        "--- /absolute/foo.py\n"
        "+++ /absolute/foo.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert any("unsafe_absolute_path" in item for item in result["warnings"])


def test_inspect_diff_warns_parent_traversal(tmp_path: Path) -> None:
    diff = (
        "diff --git a/../foo.py b/../foo.py\n"
        "--- a/../foo.py\n"
        "+++ b/../foo.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert any("unsafe_parent_traversal" in item for item in result["warnings"])


def test_inspect_diff_warns_internal_generated_paths(tmp_path: Path) -> None:
    diff = (
        "diff --git a/package.egg-info/PKG-INFO b/package.egg-info/PKG-INFO\n"
        "--- a/package.egg-info/PKG-INFO\n"
        "+++ b/package.egg-info/PKG-INFO\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert any("internal_or_generated_path" in item for item in result["warnings"])


def test_inspect_diff_large_warns(tmp_path: Path) -> None:
    changes = "".join(f"+line{i}\n-line{i}\n" for i in range(600))
    diff = (
        "diff --git a/aegis_code/huge.py b/aegis_code/huge.py\n"
        "--- a/aegis_code/huge.py\n"
        "+++ b/aegis_code/huge.py\n"
        "@@ -1 +1 @@\n"
        f"{changes}"
    )
    result = inspect_diff(diff, cwd=tmp_path)
    assert "very_large_diff" in result["warnings"]


def test_inspect_diff_invalid_when_files_present_but_zero_hunks() -> None:
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
    )
    result = inspect_diff(diff)
    assert result["valid"] is False
    assert "no_hunks" in result["errors"]


def test_inspect_diff_invalid_malformed_hunk_header() -> None:
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ ... @@\n"
        "-a\n"
        "+b\n"
    )
    result = inspect_diff(diff)
    assert result["valid"] is False
    assert "malformed_hunk_header" in result["errors"]


def test_inspect_diff_invalid_duplicate_file_blocks() -> None:
    diff = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-b\n"
        "+c\n"
    )
    result = inspect_diff(diff)
    assert result["valid"] is False
    assert "duplicate_file_targets" in result["errors"]
