from __future__ import annotations

from aegis_code.providers.base import build_diff_prompt, is_plausible_diff


def test_is_plausible_diff_accepts_common_diff_markers() -> None:
    assert is_plausible_diff("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@")
    assert is_plausible_diff("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@")
    assert is_plausible_diff("@@ -1 +1 @@\n-a\n+b")


def test_is_plausible_diff_rejects_invalid_formats() -> None:
    assert is_plausible_diff("") is False
    assert is_plausible_diff("Here is an explanation of the fix.") is False
    assert is_plausible_diff("```diff\ndiff --git a/a.py b/a.py\n```") is False


def test_build_diff_prompt_adds_test_generation_guidance() -> None:
    prompt = build_diff_prompt(
        task="add tests",
        failures={},
        context={"files": []},
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_cli.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "Prefer modifying tests only." in prompt
    assert "Put imports at the top of test files." in prompt
    assert "Produce a full-file unified diff for the test file." in prompt
    assert "Replace the entire contents of the test file." in prompt
    assert "Return exactly one diff block." in prompt
    assert "Modify only this file: tests/test_cli.py" in prompt


def test_build_diff_prompt_adds_regeneration_constraints() -> None:
    prompt = build_diff_prompt(
        task="fix tests",
        failures={},
        context={"files": []},
        patch_plan={"proposed_changes": [], "regeneration_constraints": ["Produce valid diff"]},
        aegis_execution={},
    )
    assert "Regeneration constraints:" in prompt
    assert "- Produce valid diff" in prompt
