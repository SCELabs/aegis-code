from __future__ import annotations

from aegis_code.providers.prompts import (
    build_append_prompt,
    build_create_file_prompt,
    build_insert_after_prompt,
    build_insert_before_prompt,
    build_replace_block_prompt,
)


def test_build_append_prompt_contains_key_constraints() -> None:
    prompt = build_append_prompt(
        task="append tests",
        failures={},
        context={
            "files": [],
            "repo_map": {"rendered": "Repository map (python, lightweight):\n- tests/test_cli.py"},
            "append_target_contexts": [
                {
                    "path": "tests/test_cli.py",
                    "imports": ["import pytest"],
                    "existing_names": ["test_old"],
                    "existing_tests": ["test_old"],
                    "tail": "def test_old():\n    assert True\n",
                }
            ],
            "relevant_file_snippets": [
                {"path": "tests/test_cli.py", "excerpt": "def test_old():\n    assert True\n"}
            ],
        },
        patch_plan={"allowed_targets": ["tests/test_cli.py"]},
        aegis_execution={},
    )
    assert "Return only JSON. No markdown. No explanations." in prompt
    assert '"content": "text to append at end of file"' in prompt
    assert "do not return unified diff" in prompt
    assert "- target path: tests/test_cli.py" in prompt
    assert "Do not repeat imports already present in the target file." in prompt
    assert "Do not add a test/function with a name already present." in prompt
    assert "Do not duplicate an existing workflow already covered in the target file." in prompt
    assert "Repository map:" in prompt
    assert "Snippet grounding guidance:" in prompt
    assert "Append target file context:" in prompt
    assert '{"content": ""}' in prompt


def test_build_create_file_prompt_contains_schema_and_rules() -> None:
    prompt = build_create_file_prompt(
        task="create helper",
        target_path="src/helpers.js",
        failure_context={"files": []},
        patch_plan={},
    )
    assert "Return strict JSON only. No markdown. No prose." in prompt
    assert '"content": "full file content"' in prompt
    assert "- target path: src/helpers.js" in prompt
    assert "do not return unified diff" in prompt
    assert "do not include any fields other than content" in prompt


def test_build_insert_after_prompt_contains_schema_and_anchor_rules() -> None:
    prompt = build_insert_after_prompt(
        task="insert helper",
        target_path="src/helpers.js",
        anchor="// ANCHOR",
        failure_context={"files": []},
        patch_plan={},
    )
    assert "Return strict JSON only. No markdown. No prose." in prompt
    assert '"content": "text to insert"' in prompt
    assert "- target path: src/helpers.js" in prompt
    assert "- insert after exact anchor text: // ANCHOR" in prompt
    assert "return only insertion content, not full file content" in prompt
    assert "do not include the anchor line itself in returned content" in prompt
    assert "do not include any existing line from the target file near the anchor" in prompt
    assert "do not return unified diff" in prompt


def test_build_insert_before_prompt_contains_schema_and_anchor_rules() -> None:
    prompt = build_insert_before_prompt(
        task="insert helper",
        target_path="src/helpers.js",
        anchor="// ANCHOR",
        failure_context={"files": []},
        patch_plan={},
    )
    assert "Return strict JSON only. No markdown. No prose." in prompt
    assert '"content": "text to insert"' in prompt
    assert "- target path: src/helpers.js" in prompt
    assert "- insert before exact anchor text: // ANCHOR" in prompt
    assert "return only insertion content, not full file content" in prompt
    assert "do not include the anchor line itself in returned content" in prompt
    assert "do not include any existing line from the target file near the anchor" in prompt
    assert "do not return unified diff" in prompt


def test_build_replace_block_prompt_contains_schema_and_anchor_rules() -> None:
    prompt = build_replace_block_prompt(
        task="replace block",
        target_path="src/helpers.js",
        anchor="OLD BLOCK",
        failure_context={"files": []},
        patch_plan={},
    )
    assert "Return strict JSON only. No markdown. No prose." in prompt
    assert '"content": "replacement block content"' in prompt
    assert "- target path: src/helpers.js" in prompt
    assert "- replace exact anchor block text: OLD BLOCK" in prompt
    assert "return replacement block content only, not full file content" in prompt
    assert "do not return unified diff" in prompt
