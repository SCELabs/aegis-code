from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.patches.apply_check import check_patch_file, format_apply_check_result


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
    assert "Valid: True" in formatted
    assert "Files: 1" in formatted
    assert "Hunks: 2" in formatted
    assert "Additions: 3" in formatted
    assert "Deletions: 4" in formatted
    assert "Applied: False" in formatted


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
    assert "Applied: False" in out
    assert target.read_text(encoding="utf-8") == before


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
