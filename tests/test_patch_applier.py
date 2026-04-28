from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.patches.patch_applier import apply_patch_file, format_apply_result


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_apply_valid_one_file_diff(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    _write_file(target, "def x():\n    return 1\n")
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def x():\n"
        "-    return 1\n"
        "+    return 2\n",
        encoding="utf-8",
    )
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is True
    assert result["files_changed"]
    assert "return 2" in target.read_text(encoding="utf-8")
    backup = Path(result["files_changed"][0]["backup_path"])
    assert backup.exists()


def test_apply_refuses_missing_file(tmp_path: Path) -> None:
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/missing.py b/aegis_code/missing.py\n"
        "--- a/aegis_code/missing.py\n"
        "+++ b/aegis_code/missing.py\n"
        "@@ -1 +1 @@\n"
        "-x\n"
        "+y\n",
        encoding="utf-8",
    )
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is False


def test_apply_context_mismatch_refuses(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "x.py"
    _write_file(target, "def x():\n    return 9\n")
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def x():\n"
        "-    return 1\n"
        "+    return 2\n",
        encoding="utf-8",
    )
    before = target.read_text(encoding="utf-8")
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is False
    assert target.read_text(encoding="utf-8") == before


def test_apply_unsafe_path_refuses(tmp_path: Path) -> None:
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/../x.py b/../x.py\n"
        "--- a/../x.py\n"
        "+++ b/../x.py\n"
        "@@ -1 +1 @@\n"
        "-a\n"
        "+b\n",
        encoding="utf-8",
    )
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is False
    assert "unsafe_paths" in result["errors"]


def test_apply_multi_file_success(tmp_path: Path) -> None:
    a = tmp_path / "aegis_code" / "a.py"
    b = tmp_path / "aegis_code" / "b.py"
    _write_file(a, "x=1\n")
    _write_file(b, "y=1\n")
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/a.py b/aegis_code/a.py\n"
        "--- a/aegis_code/a.py\n"
        "+++ b/aegis_code/a.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n"
        "diff --git a/aegis_code/b.py b/aegis_code/b.py\n"
        "--- a/aegis_code/b.py\n"
        "+++ b/aegis_code/b.py\n"
        "@@ -1 +1 @@\n"
        "-y=1\n"
        "+y=2\n",
        encoding="utf-8",
    )
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is True
    assert len(result["files_changed"]) == 2
    assert a.read_text(encoding="utf-8") == "x=2\n"
    assert b.read_text(encoding="utf-8") == "y=2\n"


def test_apply_multi_file_partial_failure_no_mutation(tmp_path: Path) -> None:
    a = tmp_path / "aegis_code" / "a.py"
    b = tmp_path / "aegis_code" / "b.py"
    _write_file(a, "x=1\n")
    _write_file(b, "y=9\n")
    before_a = a.read_text(encoding="utf-8")
    before_b = b.read_text(encoding="utf-8")
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/a.py b/aegis_code/a.py\n"
        "--- a/aegis_code/a.py\n"
        "+++ b/aegis_code/a.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n"
        "diff --git a/aegis_code/b.py b/aegis_code/b.py\n"
        "--- a/aegis_code/b.py\n"
        "+++ b/aegis_code/b.py\n"
        "@@ -1 +1 @@\n"
        "-y=1\n"
        "+y=2\n",
        encoding="utf-8",
    )
    result = apply_patch_file(diff, cwd=tmp_path)
    assert result["applied"] is False
    assert a.read_text(encoding="utf-8") == before_a
    assert b.read_text(encoding="utf-8") == before_b


def test_format_apply_result_contains_fields() -> None:
    text = format_apply_result(
        {
            "applied": False,
            "path": "x.diff",
            "files_changed": [],
            "warnings": ["w1"],
            "errors": ["e1"],
        }
    )
    assert "Patch apply: x.diff" in text
    assert "Applied: False" in text
    assert "Files changed: 0" in text
    assert "Warnings:" in text
    assert "Errors:" in text


def test_cli_apply_without_confirm_refuses(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    diff = tmp_path / "latest.diff"
    diff.write_text("diff --git a/x b/x\n", encoding="utf-8")
    exit_code = cli.main(["apply", str(diff)])
    out = capsys.readouterr().out
    assert exit_code != 0
    assert "requires --confirm" in out


def test_cli_apply_confirm_prints_result(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "aegis_code" / "x.py"
    _write_file(target, "x=1\n")
    diff = tmp_path / "latest.diff"
    diff.write_text(
        "diff --git a/aegis_code/x.py b/aegis_code/x.py\n"
        "--- a/aegis_code/x.py\n"
        "+++ b/aegis_code/x.py\n"
        "@@ -1 +1 @@\n"
        "-x=1\n"
        "+x=2\n",
        encoding="utf-8",
    )
    exit_code = cli.main(["apply", str(diff), "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Patch apply:" in out
    assert "Applied: True" in out

