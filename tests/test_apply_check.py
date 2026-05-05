from __future__ import annotations

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

