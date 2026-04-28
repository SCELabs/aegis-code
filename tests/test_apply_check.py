from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.patches.apply_check import check_patch_file


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
    assert "Apply is not implemented yet" in out

