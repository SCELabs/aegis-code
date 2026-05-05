from __future__ import annotations

from pathlib import Path

from aegis_code.patches.proposal_controller import (
    build_proposal_contract,
    classify_structured_failure,
    run_structured_proposal_controller,
)


def test_classify_structured_failure_mappings() -> None:
    assert classify_structured_failure(["invalid_path:outside_allowed_targets"]) == "outside_allowed_targets"
    assert classify_structured_failure(["invalid_path:parent_traversal"]) == "invalid_path"
    assert classify_structured_failure(["invalid_json"]) == "invalid_json"
    assert classify_structured_failure(["invalid_json_root"]) == "invalid_schema"
    assert classify_structured_failure(["invalid_changes"]) == "invalid_schema"
    assert classify_structured_failure(["binary_content"]) == "unsafe_content"


def test_invalid_structured_path_retries_once_and_succeeds(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_example.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_example():\n    assert 1 == 2\n", encoding="utf-8")
    contract = build_proposal_contract(
        task="add tests only",
        patch_plan={"task_type": "test_generation", "allowed_targets": ["tests/test_example.py"], "proposed_changes": [{"file": "tests/test_example.py", "change_type": "modify"}]},
        verification_command="pytest -q",
        stack_hints={},
    )
    calls = {"count": 0}

    def _attempt(_task: str) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "text": '{"changes":[{"path":"src/main.py","mode":"replace","content":"x=1\\n"}]}'}
        return {"available": True, "text": '{"changes":[{"path":"tests/test_example.py","mode":"replace","content":"def test_example():\\n    assert 1 == 1\\n"}]}'}

    result = run_structured_proposal_controller(task="fix tests", cwd=tmp_path, contract=contract, attempt_fn=_attempt)
    assert result["available"] is True
    assert result["status"] == "accepted"
    assert result["retry_count"] == 1


def test_invalid_structured_path_retries_once_and_fails_clean(tmp_path: Path) -> None:
    contract = build_proposal_contract(
        task="add tests only",
        patch_plan={"task_type": "test_generation", "allowed_targets": ["tests/test_example.py"], "proposed_changes": [{"file": "tests/test_example.py", "change_type": "modify"}]},
        verification_command="pytest -q",
        stack_hints={},
    )
    result = run_structured_proposal_controller(
        task="fix tests",
        cwd=tmp_path,
        contract=contract,
        attempt_fn=lambda _task: {"available": True, "text": '{"changes":[{"path":"src/main.py","mode":"replace","content":"x=1\\n"}]}'},
    )
    assert result["available"] is False
    assert result["status"] == "failed"
    assert result["failure_reason"] in {"invalid_path", "outside_allowed_targets"}
    assert result["retry_count"] == 1


def test_invalid_json_retries_once(tmp_path: Path) -> None:
    contract = build_proposal_contract(
        task="fix tests",
        patch_plan={"task_type": "general", "allowed_targets": [], "proposed_changes": []},
        verification_command=None,
        stack_hints={},
    )
    calls = {"count": 0}

    def _attempt(_task: str) -> dict[str, object]:
        calls["count"] += 1
        if calls["count"] == 1:
            return {"available": True, "text": "not json"}
        return {"available": True, "text": '{"changes":[{"path":"x.py","mode":"create","content":"x=1\\n"}]}'}

    result = run_structured_proposal_controller(task="x", cwd=tmp_path, contract=contract, attempt_fn=_attempt)
    assert calls["count"] == 2
    assert result["retry_count"] == 1


def test_create_target_exists_handled_safely(tmp_path: Path) -> None:
    existing = tmp_path / "README.md"
    existing.write_text("hello\n", encoding="utf-8")
    contract = build_proposal_contract(
        task="docs",
        patch_plan={"task_type": "docs_task", "allowed_targets": ["README.md"], "proposed_changes": [{"file": "README.md", "change_type": "modify"}]},
        verification_command=None,
        stack_hints={},
    )
    result = run_structured_proposal_controller(
        task="update docs",
        cwd=tmp_path,
        contract=contract,
        attempt_fn=lambda _task: {"available": True, "text": '{"changes":[{"path":"README.md","mode":"create","content":"x\\n"}]}'},
    )
    assert result["available"] is False
    assert result["failure_reason"] == "create_target_exists"


def test_replace_target_missing_handled_safely(tmp_path: Path) -> None:
    contract = build_proposal_contract(
        task="impl",
        patch_plan={"task_type": "implementation_with_tests", "allowed_targets": ["src/new.py"], "proposed_changes": [{"file": "src/new.py", "change_type": "create"}]},
        verification_command=None,
        stack_hints={},
    )
    result = run_structured_proposal_controller(
        task="add new module",
        cwd=tmp_path,
        contract=contract,
        attempt_fn=lambda _task: {"available": True, "text": '{"changes":[{"path":"src/new.py","mode":"replace","content":"x\\n"}]}'},
    )
    assert result["available"] is False
    assert result["failure_reason"] == "replace_target_missing"


def test_tests_only_task_contract_blocks_source_targets() -> None:
    contract = build_proposal_contract(
        task="add tests for save; do not modify source files",
        patch_plan={"task_type": "test_generation", "allowed_targets": ["tests/test_client.py"], "proposed_changes": [{"file": "tests/test_client.py", "change_type": "modify"}]},
        verification_command="pytest -q",
        stack_hints={},
    )
    assert contract.allowed_targets == ["tests/test_client.py"]


def test_docs_task_contract_blocks_source_and_tests_targets() -> None:
    contract = build_proposal_contract(
        task="update docs",
        patch_plan={"task_type": "docs_task", "allowed_targets": ["README.md", "docs/usage.md", "src/main.py", "tests/test_cli.py"], "proposed_changes": []},
        verification_command=None,
        stack_hints={},
    )
    assert contract.allowed_targets == ["README.md", "docs/usage.md"]
