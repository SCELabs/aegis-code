from __future__ import annotations

from aegis_code.patches.constraints import (
    build_patch_constraints,
    detect_named_test_file,
)
from aegis_code.providers.base import build_diff_prompt


def test_detect_named_test_file_handles_forward_slashes() -> None:
    task = "add one test in tests/test_client.py"
    assert detect_named_test_file(task) == "tests/test_client.py"


def test_detect_named_test_file_handles_backslashes() -> None:
    task = r"add one test in tests\test_client.py"
    assert detect_named_test_file(task) == "tests/test_client.py"


def test_build_patch_constraints_tests_only_named_file() -> None:
    task = "add tests only for behavior in tests/test_client.py without modifying source files"
    result = build_patch_constraints(task, "test_generation")
    assert result["tests_only"] is True
    assert result["target_file"] == "tests/test_client.py"
    assert result["allowed_targets"] == ["tests/test_client.py"]
    assert result["append_only"] is True
    assert result["max_deletions"] == 0


def test_build_patch_constraints_tests_only_generic_tests_target() -> None:
    task = "write tests only for existing behavior"
    result = build_patch_constraints(task, "test_generation")
    assert result["tests_only"] is True
    assert result["target_file"] is None
    assert result["allowed_targets"] == ["tests/**"]
    assert result["max_deletions"] == 0


def test_build_patch_constraints_non_test_task_unrestricted() -> None:
    result = build_patch_constraints("implement cli option", "general")
    assert result["tests_only"] is False
    assert result["allowed_targets"] == []
    assert result["max_deletions"] is None
    assert result["provider_instructions"] == []


def test_provider_prompt_uses_centralized_tests_only_constraints(monkeypatch) -> None:
    monkeypatch.setattr(
        "aegis_code.providers.base.build_patch_constraints",
        lambda **_: {
            "task_type": "test_generation",
            "tests_only": True,
            "docs_task": False,
            "allowed_targets": ["tests/test_client.py"],
            "target_file": "tests/test_client.py",
            "append_only": True,
            "max_deletions": 0,
            "allow_source_changes": False,
            "insertion_hint": "x",
            "provider_instructions": ["Custom centralized instruction."],
            "regeneration_instructions": [],
        },
    )
    prompt = build_diff_prompt(
        task="add tests only in tests/test_client.py",
        failures={},
        context={"files": [{"path": "tests/test_client.py", "content": "class TestAegisResult:\n    pass\n"}]},
        patch_plan={"task_type": "test_generation", "target_file": "tests/test_client.py", "proposed_changes": []},
        aegis_execution={},
    )
    assert "- Custom centralized instruction." in prompt

