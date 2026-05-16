from __future__ import annotations

import json
from pathlib import Path

from aegis_code import cli
from aegis_code.models import CommandResult
from aegis_code.patches.apply_check import check_patch_file, format_apply_check_result
from aegis_code.patches.patch_applier import apply_patch_file


def test_check_patch_file_valid(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("x=1\n", encoding="utf-8")
    diff_file = tmp_path / "latest.diff"
    diff_file.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is True
    assert result["applied"] is False
    assert result["summary"]["file_count"] == 1


def test_check_patch_file_empty_diff_is_invalid(tmp_path: Path) -> None:
    diff_file = tmp_path / "empty.diff"
    diff_file.write_text("", encoding="utf-8")
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert "empty_diff" in result["errors"]


def test_check_patch_file_valid_new_file_diff(tmp_path: Path) -> None:
    diff_file = tmp_path / "newfile.diff"
    diff_file.write_text(
        "diff --git a/new_module.py b/new_module.py\n"
        "--- /dev/null\n"
        "+++ b/new_module.py\n"
        "@@ -0,0 +1,2 @@\n"
        "+def created():\n"
        "+    return 1\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is True
    assert result["summary"]["file_count"] == 1
    assert result["apply_blocked"] is False


def test_check_patch_file_hunk_count_mismatch_too_many_added_lines(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("x=1\n", encoding="utf-8")
    diff_file = tmp_path / "bad_hunk.diff"
    diff_file.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1,1 +1,1 @@\n"
        "-x=1\n"
        "+x=2\n"
        "+x=3\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert "hunk_count_mismatch" in result["errors"]


def test_check_patch_file_hunk_count_mismatch_too_few_old_side_lines(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("line1\nline2\n", encoding="utf-8")
    diff_file = tmp_path / "bad_hunk_old.diff"
    diff_file.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1,2 +1,2 @@\n"
        " line1\n"
        "+line1b\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert "hunk_count_mismatch" in result["errors"]


def test_check_patch_file_blocks_internal_path(tmp_path: Path) -> None:
    diff_file = tmp_path / "unsafe.diff"
    diff_file.write_text(
        "diff --git a/.aegis/evil.txt b/.aegis/evil.txt\n"
        "--- /dev/null\n"
        "+++ b/.aegis/evil.txt\n"
        "@@ -0,0 +1 @@\n"
        "+x\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is True
    assert result["apply_blocked"] is True
    assert "unsafe_paths" in result["apply_block_reasons"]


def test_check_patch_file_blocks_absolute_path(tmp_path: Path) -> None:
    diff_file = tmp_path / "unsafe-abs.diff"
    diff_file.write_text(
        "diff --git a//tmp/evil.py b//tmp/evil.py\n"
        "--- /dev/null\n"
        "+++ /tmp/evil.py\n"
        "@@ -0,0 +1 @@\n"
        "+x=1\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["apply_blocked"] is True
    assert "unsafe_paths" in result["apply_block_reasons"]


def test_check_patch_file_blocks_parent_traversal(tmp_path: Path) -> None:
    diff_file = tmp_path / "unsafe-traversal.diff"
    diff_file.write_text(
        "diff --git a/../evil.py b/../evil.py\n"
        "--- /dev/null\n"
        "+++ b/../evil.py\n"
        "@@ -0,0 +1 @@\n"
        "+x=1\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["apply_blocked"] is True
    assert "unsafe_paths" in result["apply_block_reasons"]


def test_check_patch_file_blocks_binary_diff(tmp_path: Path) -> None:
    diff_file = tmp_path / "binary.diff"
    diff_file.write_text(
        "diff --git a/file.bin b/file.bin\n"
        "Binary files a/file.bin and b/file.bin differ\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert result["apply_blocked"] is True
    assert "invalid_diff" in result["apply_block_reasons"]


def test_check_patch_file_zero_hunks_is_blocked(tmp_path: Path) -> None:
    diff_file = tmp_path / "zero-hunks.diff"
    diff_file.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert "no_hunks" in result["errors"]
    assert result["apply_blocked"] is True


def test_check_patch_file_malformed_hunk_header_is_blocked(tmp_path: Path) -> None:
    diff_file = tmp_path / "malformed-hunk.diff"
    diff_file.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ ... @@\n"
        "-a\n"
        "+b\n",
        encoding="utf-8",
    )
    result = check_patch_file(diff_file, cwd=tmp_path)
    assert result["valid"] is False
    assert "malformed_hunk_header" in result["errors"]
    assert result["apply_blocked"] is True


def test_check_patch_file_catches_patch_applier_malformed_hunk_line(tmp_path: Path) -> None:
    target = tmp_path / "src" / "main.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("a\n", encoding="utf-8")
    diff_file = tmp_path / "malformed-hunk-line.diff"
    diff_file.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n"
        "oops\n",
        encoding="utf-8",
    )
    check = check_patch_file(diff_file, cwd=tmp_path)
    apply = apply_patch_file(diff_file, cwd=tmp_path)
    assert check["apply_blocked"] is True
    assert "invalid_diff" in check["apply_block_reasons"]
    assert "malformed_hunk_line" in check["errors"]
    assert apply["applied"] is False
    assert "malformed_hunk_line" in apply["errors"]


def test_format_apply_check_result_contains_summary_fields() -> None:
    formatted = format_apply_check_result(
        {
            "path": "x.diff",
            "valid": True,
            "summary": {"file_count": 1, "hunk_count": 2, "additions": 3, "deletions": 4},
            "warnings": [],
            "errors": [],
            "applied": False,
        }
    )
    assert "Valid: yes" in formatted
    assert "Files: 1" in formatted
    assert "Hunks: 2" in formatted
    assert "Additions: 3" in formatted
    assert "Deletions: 4" in formatted
    assert "Apply blocked: no" in formatted


def test_cli_apply_check_prints_and_does_not_modify_file(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "aegis_code" / "x.py"
    target.parent.mkdir(parents=True)
    target.write_text("x=1\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    diff_file = tmp_path / "latest.diff"
    diff_file.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )

    exit_code = cli.main(["apply", "--check", str(diff_file)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch check:" in out
    assert "Apply blocked: no" in out
    assert target.read_text(encoding="utf-8") == before


def test_cli_apply_check_marks_unsafe_paths_as_blocked(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff_file = tmp_path / "unsafe.diff"
    diff_file.write_text(
        "diff --git a/.aegis/evil.txt b/.aegis/evil.txt\n"
        "--- /dev/null\n"
        "+++ b/.aegis/evil.txt\n"
        "@@ -0,0 +1 @@\n"
        "+x\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check", str(diff_file)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "unsafe_paths" in out


def test_cli_apply_without_check_is_not_implemented(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["apply"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Patch application requires --confirm" in out


def test_cli_apply_missing_diff_path_has_helpful_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["apply", "--check", ".aegis/runs/latest.diff"])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "Diff file not found:" in out
    assert "latest.diff" in out
    assert "Run a failing task with --propose-patch first" in out


def test_apply_check_uses_latest_diff_without_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- /dev/null\n"
        "+++ b/src/main.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch check:" in out
    assert ".aegis/runs/latest.diff" in out


def test_apply_confirm_uses_latest_diff_without_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_apply(path: Path, cwd=None):
        captured["path"] = str(path)
        return {"applied": True, "path": str(path), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)
    exit_code = cli.main(["apply", "--confirm"])
    _ = capsys.readouterr().out
    assert exit_code == 0
    assert captured["path"] == str(latest)


def test_apply_confirm_run_tests_uses_latest_diff_without_path(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_apply(path: Path, cwd=None):
        captured["path"] = str(path)
        return {"applied": True, "path": str(path), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)
    monkeypatch.setattr(
        "aegis_code.cli.run_configured_tests",
        lambda _cmd, cwd=None: CommandResult(
            name="tests",
            command=_cmd,
            status="ok",
            exit_code=0,
            stdout="",
            stderr="",
            output_preview="",
            full_output="",
        ),
    )
    exit_code = cli.main(["apply", "--confirm", "--run-tests"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert captured["path"] == str(latest)
    assert "Verification:" in out
    assert "- Tests: passed" in out


def test_apply_does_not_apply_invalid_latest_diff(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.invalid.diff").write_text("not valid\n", encoding="utf-8")
    called = {"apply": False}

    def _fake_apply(path: Path, cwd=None):
        called["apply"] = True
        return {"applied": True, "path": str(path), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)
    exit_code = cli.main(["apply", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert called["apply"] is False
    assert "Status: BLOCKED" in out
    assert "Reason: no_accepted_diff" in out
    assert "- aegis-code diff --full" in out


def test_apply_check_blocks_low_safety_latest_diff(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- /dev/null\n"
        "+++ b/src/main.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text('{"apply_safety":"LOW"}', encoding="utf-8")
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_confirm_blocks_low_safety_latest_diff(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text("diff --git a/src/main.py b/src/main.py\n", encoding="utf-8")
    (runs / "latest.json").write_text('{"apply_safety":"LOW"}', encoding="utf-8")
    called = {"apply": False}

    def _fake_apply(path: Path, cwd=None):
        called["apply"] = True
        return {"applied": True, "path": str(path), "files_changed": [], "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.cli.apply_patch_file", _fake_apply)
    exit_code = cli.main(["apply", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 2
    assert called["apply"] is False
    assert "Status: BLOCKED" in out
    assert "Reason: low_safety" in out


def test_apply_check_allows_bounded_fix_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    return a + b\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "fix failing tests in tests/test_calculator.py",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "summary": {"additions": 1, "deletions": 1},
                        "files": [{"old_path": "src/calculator.py", "new_path": "src/calculator.py"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Valid: yes" in out
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_replace_block_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text(
        "def add_note(notes, text):\n    return notes + [text]\n",
        encoding="utf-8",
    )
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,5 @@\n"
        " def add_note(notes, text):\n"
        "-    return notes + [text]\n"
        "+    cleaned = text.strip()\n"
        "+    if not cleaned:\n"
        "+        return notes\n"
        "+    return notes + [cleaned]\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "replace block in add_note",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "replace-block", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 4, "deletions": 1},
                        "files": [{"old_path": "src/main.py", "new_path": "src/main.py"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_append_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "notes.test.js").write_text("import test from 'node:test';\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/tests/notes.test.js b/tests/notes.test.js\n"
        "--- a/tests/notes.test.js\n"
        "+++ b/tests/notes.test.js\n"
        "@@ -1 +1,2 @@\n"
        " import test from 'node:test';\n"
        "+test('placeholder', () => {});\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "append one test",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "append", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "tests/notes.test.js", "new_path": "tests/notes.test.js"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_create_file_low_safety_override_real_latest_json_flow(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/docs/search-notes.md b/docs/search-notes.md\n"
        "new file mode 100644\n"
        "--- a/docs/search-notes.md\n"
        "+++ b/docs/search-notes.md\n"
        "@@ -0,0 +1,3 @@\n"
        "+# Search Notes\n"
        "+\n"
        "+Use `searchNotes(notes, query)` to filter notes by term.\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "create docs file",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "create-file", "source": "cli"},
                "patch_plan": {"allow_new_files": True, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": "docs_language_mismatch"},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 3, "deletions": 0},
                        "files": [{"old_path": "/dev/null", "new_path": "docs/search-notes.md", "exists": False}],
                        "warnings": ["referenced file missing: docs/search-notes.md"],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_create_file_missing_target_warning_is_informational(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/docs/search-notes.md b/docs/search-notes.md\n"
        "new file mode 100644\n"
        "--- a/docs/search-notes.md\n"
        "+++ b/docs/search-notes.md\n"
        "@@ -0,0 +1 @@\n"
        "+# Search Notes\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "create docs file",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "create-file", "source": "cli"},
                "patch_plan": {"allow_new_files": True, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": "docs_language_mismatch"},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "/dev/null", "new_path": "docs/search-notes.md", "exists": False}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "referenced file missing: docs/search-notes.md" in out
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_replace_file_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(text) {\n  return text;\n}\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,7 @@\n"
        " export function addNote(text) {\n"
        "-  return text;\n"
        "+  const value = text.trim();\n"
        "+  if (!value) {\n"
        "+    throw new Error('note text required');\n"
        "+  }\n"
        "+  return value;\n"
        " }\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "replace file content for addNote hardening",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "replace-file", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": None},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 5, "deletions": 1},
                        "files": [{"old_path": "src/notes.js", "new_path": "src/notes.js", "exists": True}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_delete_file_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "obsolete.md").write_text("# Obsolete\n\nremove me\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/docs/obsolete.md b/docs/obsolete.md\n"
        "deleted file mode 100644\n"
        "--- a/docs/obsolete.md\n"
        "+++ /dev/null\n"
        "@@ -1,3 +0,0 @@\n"
        "-# Obsolete\n"
        "-\n"
        "-remove me\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "delete obsolete docs file",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "delete-file", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": None},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 0, "deletions": 3},
                        "files": [{"old_path": "docs/obsolete.md", "new_path": None, "exists": True}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_allows_controlled_replace_symbol_low_safety_override(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(text) {\n  return text;\n}\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,7 @@\n"
        " export function addNote(text) {\n"
        "-  return text;\n"
        "+  const value = text.trim();\n"
        "+  if (!value) {\n"
        "+    throw new Error('note text required');\n"
        "+  }\n"
        "+  return value;\n"
        " }\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "rewrite addNote symbol",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "replace-symbol", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": None},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 5, "deletions": 1},
                        "files": [{"old_path": "src/notes.js", "new_path": "src/notes.js", "exists": True}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: no" in out
    assert "low_safety" not in out


def test_apply_check_keeps_low_safety_block_for_unsafe_replace_symbol(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(text) {\n  return text;\n}\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,4 @@\n"
        " export function addNote(text) {\n"
        "-  return text;\n"
        "+  const subprocess = require('child_process');\n"
        "+  return text;\n"
        " }\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "rewrite addNote symbol",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "replace-symbol", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": None},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 2, "deletions": 1},
                        "files": [{"old_path": "src/notes.js", "new_path": "src/notes.js", "exists": True}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_keeps_low_safety_block_for_create_file_when_target_exists(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "search-notes.md").write_text("# Existing\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/docs/search-notes.md b/docs/search-notes.md\n"
        "new file mode 100644\n"
        "--- a/docs/search-notes.md\n"
        "+++ b/docs/search-notes.md\n"
        "@@ -0,0 +1 @@\n"
        "+# Search Notes\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "create docs file",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "create-file", "source": "cli"},
                "patch_plan": {"allow_new_files": True, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": "docs_language_mismatch"},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "/dev/null", "new_path": "docs/search-notes.md", "exists": True}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_non_create_file_missing_reference_still_blocks_low_safety(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/missing.py b/src/missing.py\n"
        "--- a/src/missing.py\n"
        "+++ b/src/missing.py\n"
        "@@ -1 +1,2 @@\n"
        " x = 1\n"
        "+y = 2\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "append line",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "append", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "policy_diagnostics": {"final_policy_reason": None},
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "src/missing.py", "new_path": "src/missing.py", "exists": False}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "referenced file missing: src/missing.py" in out
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_keeps_low_safety_block_for_unsafe_replace_block(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "main.py").write_text("def fn():\n    return 1\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "--- a/src/main.py\n"
        "+++ b/src/main.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def fn():\n"
        "+    import subprocess\n"
        "     return 1\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "replace block in fn",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "replace-block", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "src/main.py", "new_path": "src/main.py"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_keeps_low_safety_block_for_insert_after_even_when_structural_checks_pass(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "notes.js").write_text("export function addNote(notes, text) {\n  return notes;\n}\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/notes.js b/src/notes.js\n"
        "--- a/src/notes.js\n"
        "+++ b/src/notes.js\n"
        "@@ -1,3 +1,4 @@\n"
        " export function addNote(notes, text) {\n"
        "+  const normalized = text.trim();\n"
        "   return notes;\n"
        " }\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "insert helper",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_operation": {"operation": "insert-after", "source": "cli"},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "valid": True,
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "src/notes.js", "new_path": "src/notes.js"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_keeps_low_safety_block_for_shell_additions(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,3 @@\n"
        " def add(a, b):\n"
        "+    import subprocess\n"
        "     return a - b\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "fix failing tests in tests/test_calculator.py",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "summary": {"additions": 1, "deletions": 0},
                        "files": [{"old_path": "src/calculator.py", "new_path": "src/calculator.py"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out


def test_apply_check_keeps_low_safety_block_for_broad_rewrite(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    latest = runs / "latest.diff"
    latest.write_text(
        "diff --git a/src/calculator.py b/src/calculator.py\n"
        "--- a/src/calculator.py\n"
        "+++ b/src/calculator.py\n"
        "@@ -1,2 +1,8 @@\n"
        " def add(a, b):\n"
        "-    return a - b\n"
        "+    x = a + b\n"
        "+    y = x * 2\n"
        "+    z = y - 1\n"
        "+    q = z + 3\n"
        "+    w = q * 4\n"
        "+    return w\n",
        encoding="utf-8",
    )
    (runs / "latest.json").write_text(
        json.dumps(
            {
                "task": "fix failing tests in tests/test_calculator.py",
                "apply_safety": "LOW",
                "patch_safety": {"highest_severity": "pass", "issues": []},
                "patch_plan": {"allow_new_files": False, "max_files": 1},
                "patch_diff": {
                    "path": str(latest),
                    "plan_consistent": True,
                    "validation_result": {
                        "summary": {"additions": 6, "deletions": 1},
                        "files": [{"old_path": "src/calculator.py", "new_path": "src/calculator.py"}],
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", "--check"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Apply blocked: yes" in out
    assert "low_safety" in out

