from __future__ import annotations

from aegis_code.providers.base import _trim_context, build_diff_prompt, is_plausible_diff
from aegis_code.providers.context_builder import build_failure_fix_context


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
        task="add one small test for AegisResult.debug_summary in tests/test_cli.py without removing or rewriting existing tests",
        failures={},
        context={
            "files": [
                {
                    "path": "tests/test_cli.py",
                    "content": "import pytest\n\nclass TestCli:\n    def test_old(self):\n        assert True\n",
                }
            ]
        },
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_cli.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "Prefer modifying tests only." in prompt
    assert "Append-only test addition unless the task explicitly asks to edit existing tests." in prompt
    assert "Do not delete existing tests." in prompt
    assert "Do not rewrite whole files." in prompt
    assert "Do not replace imports unless required." in prompt
    assert "Add the smallest possible test." in prompt
    assert "Output a valid unified diff only." in prompt
    assert "Modify only this file: tests/test_cli.py" in prompt
    assert "Max deletions: 0" in prompt
    assert "Named target file: tests/test_cli.py" in prompt


def test_named_test_file_context_does_not_cut_mid_line() -> None:
    long_tail = "\n".join(f"def test_item_{idx}():\n    assert {idx} == {idx}" for idx in range(120))
    prompt = build_diff_prompt(
        task="add one test for AegisResult.debug_summary in tests/test_client.py",
        failures={},
        context={
            "files": [
                {
                    "path": "tests/test_client.py",
                    "content": (
                        "import os\nfrom app import x\n\nclass TestAegisResult:\n"
                        "    def test_summary(self):\n"
                        "        self.assertTrue(all(isinstance(x, str) for x in ['a']))\n\n"
                        + long_tail
                        + "\nself.assertTrue(all(isinstan"
                    ),
                },
                {"path": "tests/test_other.py", "content": "import pytest\n"},
            ]
        },
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_client.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "self.assertTrue(all(isinstan" not in prompt
    assert "[truncated]" not in prompt


def test_provider_context_never_cuts_mid_line() -> None:
    content = "first line\nsecond line\nthird line\n"
    trimmed = _trim_context({"files": [{"path": "tests/test_a.py", "content": content}]}, 18)
    emitted = str(trimmed["files"][0]["content"])
    assert "second line" not in emitted
    assert emitted.endswith("chars omitted]")
    assert "second li" not in emitted


def test_named_test_file_context_includes_test_class_anchor() -> None:
    content = (
        "import os\nfrom app import x\n\nclass TestAegisResult:\n"
        "    def test_summary(self):\n        assert True\n\n"
        "    def test_debug_summary(self):\n        assert True\n\n"
        "class TestOther:\n    def test_other(self):\n        assert True\n"
    )
    prompt = build_diff_prompt(
        task="add one test for AegisResult.debug_summary in tests/test_client.py",
        failures={},
        context={"files": [{"path": "tests/test_client.py", "content": content}]},
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_client.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "'header': 'class TestAegisResult:'" in prompt
    assert "'methods': ['def test_summary(self):', 'def test_debug_summary(self):']" in prompt
    assert "'path': 'tests/test_client.py'" in prompt
    assert "'imports': ['import os', 'from app import x']" in prompt
    assert "'symbols': ['class TestAegisResult:'" in prompt
    assert "tests/test_other.py" not in prompt
    assert (
        "Append a new test method at the end of class TestAegisResult."
        in prompt
    )


def test_tests_only_named_file_context_does_not_include_partial_code() -> None:
    prompt = build_diff_prompt(
        task="add one test for AegisResult.debug_summary in tests/test_client.py",
        failures={},
        context={
            "files": [
                {
                    "path": "tests/test_client.py",
                    "content": (
                        "class TestAegisResult:\n"
                        "    def test_summary(self):\n"
                        "        assert True\n"
                        "self.assertTrue(all(isinstan"
                    ),
                }
            ]
        },
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_client.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "self.assertTrue(all(isinstan" not in prompt


def test_tests_only_prompt_includes_real_hunk_header_instruction() -> None:
    prompt = build_diff_prompt(
        task="add one test for AegisResult.debug_summary in tests/test_client.py",
        failures={},
        context={"files": [{"path": "tests/test_client.py", "content": "class TestAegisResult:\n    pass\n"}]},
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_client.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "Do not use placeholder hunk headers such as @@ ... @@." in prompt
    assert "Use a real unified diff hunk header with line numbers." in prompt


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


def test_build_diff_prompt_adds_docs_guidance_for_readme_tasks() -> None:
    prompt = build_diff_prompt(
        task="update README with examples for cli usage",
        failures={},
        context={"files": []},
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "README.md", "change_type": "modify"}]},
        aegis_execution={},
    )
    assert "Return ONLY a valid unified diff." in prompt
    assert "Target README.md." in prompt
    assert "Do not output explanation." in prompt
    assert "Do not modify source or tests unless explicitly requested." in prompt
    assert "diff --git a/README.md b/README.md" in prompt
    assert "--- a/README.md" in prompt
    assert "+++ b/README.md" in prompt
    assert "--- /dev/null" in prompt
    assert "+++ b/README.md" in prompt


def test_build_diff_prompt_non_test_task_unaffected() -> None:
    prompt = build_diff_prompt(
        task="implement cli status output",
        failures={},
        context={"files": [{"path": "src/main.py", "content": "def main():\n    pass\n"}]},
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "src/main.py", "change_type": "modify"}]},
        aegis_execution={},
    )
    assert "Append-only test addition unless the task explicitly asks to edit existing tests." not in prompt
    assert "Do not delete existing tests." not in prompt
    assert "Context: {'files': [{'path': 'src/main.py', 'content': 'def main():\\n    pass\\n'}]}" in prompt


def test_fix_context_extracts_failing_test_function() -> None:
    content = (
        "import pytest\n\n"
        "def test_alpha():\n"
        "    assert True\n\n"
        "def test_aegis_intentional_semantic_failure():\n"
        "    from aegis import AegisResult\n"
        "    result = AegisResult(scope='llm')\n"
        "    assert result.debug_summary() == 'wrong'\n\n"
        "def test_omega():\n"
        "    assert True\n"
    )
    shaped = build_failure_fix_context(
        context={"files": [{"path": "tests/test_client.py", "content": content}]},
        target_file="tests/test_client.py",
        failing_nodeid="tests/test_client.py::test_aegis_intentional_semantic_failure",
        failing_error="AssertionError: - wrong + scope=llm actions=0 trace_steps=0 used_fallback=no",
    )
    files = shaped.get("files", [])
    assert isinstance(files, list) and files
    block = files[0]
    source = str(block.get("failing_test_source", ""))
    assert "def test_aegis_intentional_semantic_failure" in source
    assert "def test_alpha" not in source
    assert "def test_omega" not in source


def test_fix_prompt_for_assertion_mismatch_limits_target_to_failing_test_file() -> None:
    prompt = build_diff_prompt(
        task="fix failing tests in tests/test_client.py; target failing test tests/test_client.py::test_aegis_intentional_semantic_failure",
        failures={},
        context={
            "files": [
                {"path": "tests/test_client.py", "content": "def test_aegis_intentional_semantic_failure():\n    assert True\n"},
                {"path": "tests/test_other.py", "content": "def test_other():\n    assert True\n"},
            ]
        },
        patch_plan={
            "task_type": "test_generation",
            "target_file": "tests/test_client.py",
            "allowed_targets": ["tests/test_client.py"],
            "failing_test_nodeid": "tests/test_client.py::test_aegis_intentional_semantic_failure",
            "failing_test_error": "AssertionError: x",
            "proposed_changes": [],
        },
        aegis_execution={},
    )
    assert "Allowed-target guidance:" in prompt
    assert "Modify only these files: tests/test_client.py" in prompt
    assert "tests/test_other.py" not in prompt


def test_fix_prompt_prefers_assertion_update_when_actual_output_visible() -> None:
    prompt = build_diff_prompt(
        task="fix failing tests in tests/test_client.py; assertion mismatch",
        failures={},
        context={"files": [{"path": "tests/test_client.py", "content": "def test_x():\n    assert True\n"}]},
        patch_plan={
            "task_type": "test_generation",
            "target_file": "tests/test_client.py",
            "failing_test_nodeid": "tests/test_client.py::test_x",
            "failing_test_error": "AssertionError: - wrong + scope=llm actions=0 trace_steps=0 used_fallback=no",
            "proposed_changes": [],
        },
        aegis_execution={},
    )
    assert "Prefer updating the assertion expected value if implementation behavior is clearly shown by pytest." in prompt


def test_fix_context_does_not_include_entire_large_test_file() -> None:
    large = "\n".join(f"def test_noise_{i}():\n    assert True\n" for i in range(200))
    content = (
        "import pytest\n\n"
        + large
        + "\n"
        + "def test_aegis_intentional_semantic_failure():\n"
        + "    assert 'actual' == 'wrong'\n"
        + "\n"
        + large
    )
    shaped = build_failure_fix_context(
        context={"files": [{"path": "tests/test_client.py", "content": content}]},
        target_file="tests/test_client.py",
        failing_nodeid="tests/test_client.py::test_aegis_intentional_semantic_failure",
        failing_error="AssertionError: mismatch",
    )
    source = str(shaped["files"][0].get("failing_test_source", ""))
    assert "def test_aegis_intentional_semantic_failure" in source
    assert "test_noise_0" not in source
