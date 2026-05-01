from __future__ import annotations

from aegis_code.patches.diff_normalizer import normalize_unified_diff


def test_normalize_diff_adds_header() -> None:
    raw = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    normalized = normalize_unified_diff(raw)
    assert normalized.startswith("diff --git a/src/main.py b/src/main.py\n")


def test_existing_diff_header_unchanged() -> None:
    raw = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
    )
    normalized = normalize_unified_diff(raw)
    assert normalized == raw


def test_multi_file_diff_normalized() -> None:
    raw = (
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "--- a/tests/test_main.py\n"
        "+++ b/tests/test_main.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n"
    )
    normalized = normalize_unified_diff(raw)
    assert "diff --git a/src/main.py b/src/main.py" in normalized
    assert "diff --git a/tests/test_main.py b/tests/test_main.py" in normalized


def test_new_file_diff_normalized() -> None:
    raw = (
        "--- /dev/null\n"
        "+++ b/src/helper.py\n"
        "@@ -0,0 +1 @@\n"
        "+x=1\n"
    )
    normalized = normalize_unified_diff(raw)
    assert normalized.startswith("diff --git a/src/helper.py b/src/helper.py\n")
    assert "--- /dev/null\n+++ b/src/helper.py\n" in normalized
