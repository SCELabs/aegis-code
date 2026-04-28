from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.patches.backups import list_backups, restore_backup


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_backups_none(tmp_path: Path, monkeypatch, capsys) -> None:
    result = list_backups(tmp_path)
    assert result["backups"] == []
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["backups"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No backups found." in out


def test_list_backups_sorted_newest_first(tmp_path: Path) -> None:
    newer = tmp_path / ".aegis" / "backups" / "20260428_143210"
    older = tmp_path / ".aegis" / "backups" / "20260427_101010"
    _write(newer / "aegis_code/runtime.py", "x\n")
    _write(older / "aegis_code/runtime.py", "y\n")
    result = list_backups(tmp_path)
    assert result["backups"][0]["id"] == "20260428_143210"
    assert result["backups"][1]["id"] == "20260427_101010"


def test_restore_valid_backup(tmp_path: Path) -> None:
    target = tmp_path / "aegis_code" / "runtime.py"
    _write(target, "current\n")
    backup = tmp_path / ".aegis" / "backups" / "20260428_143210" / "aegis_code" / "runtime.py"
    _write(backup, "original\n")
    result = restore_backup("20260428_143210", tmp_path)
    assert result["restored"] is True
    assert "aegis_code/runtime.py" in result["files"]
    assert target.read_text(encoding="utf-8") == "original\n"


def test_restore_missing_backup(tmp_path: Path) -> None:
    result = restore_backup("20260428_143210", tmp_path)
    assert result["restored"] is False
    assert "backup_not_found" in result["errors"]


def test_restore_rejects_unsafe_backup_id(tmp_path: Path) -> None:
    for value in ("../x", "/abs/path", "foo/bar", "foo\\bar"):
        result = restore_backup(value, tmp_path)
        assert result["restored"] is False
        assert "invalid_backup_id" in result["errors"]


def test_restore_nested_file_creates_parent_dirs(tmp_path: Path) -> None:
    backup = tmp_path / ".aegis" / "backups" / "20260428_143210" / "nested" / "a.py"
    _write(backup, "nested\n")
    result = restore_backup("20260428_143210", tmp_path)
    assert result["restored"] is True
    assert (tmp_path / "nested" / "a.py").read_text(encoding="utf-8") == "nested\n"


def test_apply_preview_without_confirm_does_not_modify(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "aegis_code" / "x.py"
    _write(target, "x=1\n")
    before = target.read_text(encoding="utf-8")
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
    exit_code = cli.main(["apply", str(diff)])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "Patch preview:" in out
    assert "Use --confirm to apply this patch." in out
    assert target.read_text(encoding="utf-8") == before


def test_confirmed_apply_creates_backup_visible_in_list(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "aegis_code" / "x.py"
    _write(target, "x=1\n")
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
    assert cli.main(["apply", str(diff), "--confirm"]) == 0
    backups = list_backups(tmp_path)["backups"]
    assert backups
    assert any("aegis_code/x.py" in item["files"] for item in backups)


def test_restore_from_apply_created_backup_restores_original(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "aegis_code" / "x.py"
    _write(target, "x=1\n")
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
    assert cli.main(["apply", str(diff), "--confirm"]) == 0
    backups = list_backups(tmp_path)["backups"]
    backup_id = backups[0]["id"]
    assert target.read_text(encoding="utf-8") == "x=2\n"
    restored = restore_backup(backup_id, tmp_path)
    assert restored["restored"] is True
    assert target.read_text(encoding="utf-8") == "x=1\n"

