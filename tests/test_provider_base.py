from __future__ import annotations

from aegis_code.providers.base import is_plausible_diff


def test_is_plausible_diff_accepts_common_diff_markers() -> None:
    assert is_plausible_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@")
    assert is_plausible_diff("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@")
    assert is_plausible_diff("@@ -1 +1 @@\n-a\n+b")


def test_is_plausible_diff_rejects_invalid_formats() -> None:
    assert is_plausible_diff("") is False
    assert is_plausible_diff("Here is an explanation of the fix.") is False
    assert is_plausible_diff("```diff\ndiff --git a/a.py b/a.py\n```") is False

