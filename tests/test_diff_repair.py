from __future__ import annotations

from pathlib import Path

import aegis_code.patches.diff_repair as diff_repair_module
from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.patch_applier import apply_patch_file
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
    assert result["reason"] == "file_count_out_of_scope"


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


def test_impl_with_tests_multi_file_create_repaired(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.lower().replace(' ', '-')\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+from src.helpers import slugify\n"
        "+\n"
        "+def test_slugify_spaces():\n"
        "+    assert slugify('Hello World') == 'hello-world'\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add a helpers module with a slugify(text) function and tests for it",
        patch_plan={
            "task_type": "implementation_with_tests",
            "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}],
        },
        context={"files": []},
    )
    assert result["applied"] is True
    assert result["repair_file_count"] == 2
    assert sorted(result["repair_targets"]) == ["src/helpers.py", "tests/test_helpers.py"]
    repaired = str(result["diff"])
    assert "diff --git a/src/helpers.py b/src/helpers.py" in repaired
    assert "diff --git a/tests/test_helpers.py b/tests/test_helpers.py" in repaired
    assert inspect_diff(repaired, cwd=tmp_path)["valid"] is True


def test_impl_with_tests_repair_uses_diff_git_target_for_new_file_headers(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/test\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.lower().replace(' ', '-')\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/test\n"
        "@@ -0,0 +1,1 @@\n"
        "+from src.helpers import slugify\n"
        "+\n"
        "+def test_slugify_spaces():\n"
        "+    assert slugify('Hello World') == 'hello-world'\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add a helpers module with a slugify(text) function and tests for it",
        patch_plan={
            "task_type": "implementation_with_tests",
            "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}],
        },
        context={"files": []},
    )
    assert result["applied"] is True
    repaired = str(result["diff"])
    assert "+++ b/src/helpers.py" in repaired
    assert "+++ b/tests/test_helpers.py" in repaired
    assert "+++ b/test\n" not in repaired
    assert sorted(result["repair_targets"]) == ["src/helpers.py", "tests/test_helpers.py"]
    assert inspect_diff(repaired, cwd=tmp_path)["valid"] is True


def test_repaired_new_file_diff_has_dev_null_header_prefix(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.lower()\n"
        "+\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper module",
        patch_plan={"task_type": "general", "proposed_changes": [{"file": "src/helpers.py"}]},
        context={"files": []},
    )
    assert result["applied"] is True
    repaired = str(result["diff"])
    assert "--- /dev/null\n+++ b/src/helpers.py" in repaired
    assert "\n/dev/null\n+++ b/src/helpers.py" not in repaired


def test_repaired_multi_file_create_diff_check_and_apply_consistent(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.lower().replace(' ', '-')\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+from src.helpers import slugify\n"
        "+\n"
        "+def test_slugify_spaces():\n"
        "+    assert slugify('Hello World') == 'hello-world'\n"
    )
    repaired_result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add a helpers module with tests",
        patch_plan={
            "task_type": "implementation_with_tests",
            "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}],
        },
        context={"files": []},
    )
    assert repaired_result["applied"] is True
    repaired = str(repaired_result["diff"])
    assert "--- /dev/null\n+++ b/src/helpers.py" in repaired
    assert "--- /dev/null\n+++ b/tests/test_helpers.py" in repaired
    assert "\n/dev/null\n+++ b/" not in repaired

    check_result = check_patch_text(repaired, cwd=tmp_path)
    assert check_result["valid"] is True
    assert check_result["apply_blocked"] is False

    diff_file = tmp_path / "latest.diff"
    diff_file.write_text(repaired, encoding="utf-8")
    apply_result = apply_patch_file(diff_file, cwd=tmp_path)
    assert apply_result["applied"] is True
    assert sorted(str(item) for item in apply_result["files_changed"]) == ["src/helpers.py", "tests/test_helpers.py"]


def test_incidental_triple_plus_minus_in_code_not_new_block(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+TEXT = '--- not a header and +++ not a header'\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def test_text():\n"
        "+    assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={"task_type": "implementation_with_tests", "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}]},
        context={"files": []},
    )
    assert result["repair_file_count"] == 2
    assert result["raw_repair_file_count"] == 2


def test_duplicate_blocks_dedup_by_target_repairs(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def test_slugify():\n"
        "+    assert True\n"
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.strip()\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def test_slugify_spaces():\n"
        "+    assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={"task_type": "implementation_with_tests", "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}]},
        context={"files": []},
    )
    assert result["applied"] is True
    assert result["raw_repair_file_count"] == 4
    assert result["repair_file_count"] == 2
    assert sorted(result["repair_targets"]) == ["src/helpers.py", "tests/test_helpers.py"]


def test_impl_with_tests_mixed_create_modify_repaired(tmp_path: Path) -> None:
    existing = tmp_path / "tests" / "test_helpers.py"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- a/tests/test_helpers.py\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -1,1 +1,1 @@\n"
        " def test_smoke():\n"
        "+def test_slugify():\n"
        "+    assert True\n"
        "     assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={
            "task_type": "implementation_with_tests",
            "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}],
        },
        context={"files": [{"path": "tests/test_helpers.py", "content": existing.read_text(encoding="utf-8")}]},
    )
    assert result["applied"] is True
    assert inspect_diff(result["diff"], cwd=tmp_path)["valid"] is True


def test_impl_with_tests_out_of_scope_file_count_skipped(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n--- /dev/null\n+++ b/src/helpers.py\n@@ -0,0 +1,1 @@\n+a\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n--- /dev/null\n+++ b/tests/test_helpers.py\n@@ -0,0 +1,1 @@\n+b\n"
        "diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,1 +1,1 @@\n-c\n+d\n+e\n"
        "diff --git a/src/extra.py b/src/extra.py\n--- /dev/null\n+++ b/src/extra.py\n@@ -0,0 +1,1 @@\n+z\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={
            "task_type": "implementation_with_tests",
            "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}, {"file": "README.md"}, {"file": "src/extra.py"}],
        },
        context={"files": []},
    )
    assert result["applied"] is False
    assert result["status"] == "skipped"
    assert result["reason"] == "file_count_out_of_scope"
    assert result["repair_file_count"] == 4


def test_impl_with_tests_two_file_hunk_mismatch_not_file_count_skip(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def test_slugify():\n"
        "+    assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={"task_type": "implementation_with_tests", "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}]},
        context={"files": []},
    )
    assert result["reason"] != "file_count_out_of_scope"


def test_impl_with_tests_skipped_when_target_not_in_plan(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text\n"
        "diff --git a/tests/test_helpers.py b/tests/test_helpers.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def test_slugify():\n"
        "+    assert True\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={"task_type": "implementation_with_tests", "proposed_changes": [{"file": "src/helpers.py"}]},
        context={"files": []},
    )
    assert result["applied"] is False
    assert result["status"] == "skipped"
    assert result["reason"] == "target_not_in_plan"


def test_duplicate_block_target_not_in_plan_fails(tmp_path: Path) -> None:
    malformed = (
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text\n"
        "diff --git a/src/other.py b/src/other.py\n"
        "--- /dev/null\n"
        "+++ b/src/other.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+x = 1\n"
        "diff --git a/src/helpers.py b/src/helpers.py\n"
        "--- /dev/null\n"
        "+++ b/src/helpers.py\n"
        "@@ -0,0 +1,1 @@\n"
        "+def slugify(text):\n"
        "+    return text.strip()\n"
    )
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add helper and tests",
        patch_plan={"task_type": "implementation_with_tests", "proposed_changes": [{"file": "src/helpers.py"}, {"file": "tests/test_helpers.py"}]},
        context={"files": []},
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "target_not_in_plan"


def test_repair_validation_failed_reason(tmp_path: Path, monkeypatch) -> None:
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
    original_inspect = diff_repair_module.inspect_diff
    call_count = {"n": 0}

    def _inspect(diff: str, cwd: Path | None = None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return original_inspect(diff, cwd=cwd)
        return {"valid": False, "errors": ["forced_invalid"], "warnings": [], "files": []}

    monkeypatch.setattr(diff_repair_module, "inspect_diff", _inspect)
    result = repair_malformed_diff(
        malformed,
        cwd=tmp_path,
        task="add tests",
        patch_plan={"task_type": "test_generation"},
        context={"files": []},
    )
    assert result["applied"] is False
    assert result["status"] == "failed"
    assert result["reason"] == "validation_failed"
