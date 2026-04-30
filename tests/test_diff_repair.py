from __future__ import annotations

from pathlib import Path

from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.diff_repair import repair_malformed_diff


def test_malformed_hunk_repaired_to_valid(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_cli_placeholder():\n    assert True\n", encoding="utf-8")
    malformed = (
        "diff --git a/tests/test_cli.py b/tests/test_cli.py\n"
        "--- a/tests/test_cli.py\n"
        "+++ b/tests/test_cli.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def test_cli_placeholder():\n"
        "+import os\n"
        "+\n"
        "+def test_new():\n"
        "+    assert os is not None\n"
        "     assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add tests for cli behavior",
        patch_plan={"task_type": "test_generation"},
        context={"files": [{"path": "tests/test_cli.py", "content": target.read_text(encoding="utf-8")}]},
    )
    assert result["applied"] is True
    assert result["status"] == "repaired"
    assert inspect_diff(result["diff"], cwd=tmp_path)["valid"] is True


def test_malformed_multi_file_diff_skipped(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/tests/test_cli.py b/tests/test_cli.py\n"
        "--- a/tests/test_cli.py\n"
        "+++ b/tests/test_cli.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+b\n"
        "diff --git a/tests/test_other.py b/tests/test_other.py\n"
        "--- a/tests/test_other.py\n"
        "+++ b/tests/test_other.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-c\n"
        "+d\n"
        "+e\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add tests",
        patch_plan={"task_type": "test_generation"},
        context={"files": []},
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "not_single_file_target"


def test_non_test_task_skipped(tmp_path: Path) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    malformed = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,1 +1,1 @@\n"
        " def run():\n"
        "+def complete(item):\n"
        "+    return True\n"
        "     return 1\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="implement feature",
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "src/main.py"}]},
        context={"files": [{"path": "src/main.py", "content": target.read_text(encoding="utf-8")}]},
    )
    assert result["status"] == "repaired"
    assert result["applied"] is True


def test_repair_produces_valid_unified_diff(tmp_path: Path) -> None:
    target = tmp_path / "tests" / "test_cli.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_cli_placeholder():\n    assert True\n", encoding="utf-8")
    malformed = (
        "diff --git a/tests/test_cli.py b/tests/test_cli.py\n"
        "--- a/tests/test_cli.py\n"
        "+++ b/tests/test_cli.py\n"
        "@@ -1,1 +1,1 @@\n"
        " def test_cli_placeholder():\n"
        "+import os\n"
        "     assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add tests",
        patch_plan={"task_type": "test_generation"},
        context={"files": []},
    )
    assert result["applied"] is True
    repaired = str(result["diff"])
    assert repaired.startswith("diff --git a/tests/test_cli.py b/tests/test_cli.py\n")
    assert inspect_diff(repaired, cwd=tmp_path)["valid"] is True


def test_malformed_diff_touching_unrelated_file_skips(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "notes.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a\n", encoding="utf-8")
    malformed = (
        "diff --git a/docs/notes.md b/docs/notes.md\n"
        "--- a/docs/notes.md\n"
        "+++ b/docs/notes.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+b\n"
        "+c\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="implement feature",
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "src/main.py"}]},
        context={"files": [{"path": "src/main.py", "content": ""}]},
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "target_not_allowed_path"


def test_unsafe_internal_generated_path_skips(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/.aegis/state.json b/.aegis/state.json\n"
        "--- a/.aegis/state.json\n"
        "+++ b/.aegis/state.json\n"
        "@@ -1,1 +1,1 @@\n"
        "-a\n"
        "+b\n"
        "+c\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="implement feature",
        patch_plan={"task_type": "general", "proposed_changes": [{"file": ".aegis/state.json"}]},
        context={"files": []},
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "unsafe_or_internal_target"


def test_repaired_feature_diff_passes_inspect_check(tmp_path: Path) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def run():\n    return 1\n", encoding="utf-8")
    malformed = (
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,1 +1,1 @@\n"
        " def run():\n"
        "+def complete(item):\n"
        "+    return item\n"
        "     return 1\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add a feature to mark a todo item complete",
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "src/main.py"}]},
        context={"files": [{"path": "src/main.py", "content": target.read_text(encoding="utf-8")}]},
    )
    assert result["applied"] is True
    assert inspect_diff(result["diff"], cwd=tmp_path)["valid"] is True
