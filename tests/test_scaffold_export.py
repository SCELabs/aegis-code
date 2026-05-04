from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.scaffold_export import export_scaffold_profile


def test_exports_profile_from_simple_repo(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    assert result["file_count"] == 2
    text = output.read_text(encoding="utf-8")
    assert "name: repo" in text
    assert "path: README.md" in text
    assert "path: src/main.py" in text


def test_absolute_source_and_output_paths_allowed(tmp_path: Path) -> None:
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    output = tmp_path / "exported" / "profile.yml"
    result = export_scaffold_profile(source.resolve(), output.resolve())
    assert result["ok"] is True
    assert output.exists()


def test_windows_style_absolute_path_not_rejected_as_unsafe(tmp_path: Path) -> None:
    # On non-Windows this path won't exist; we only assert it is not rejected
    # by an absolute-path safety gate.
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("C:\\Users\\me\\repo"), output)
    assert result["ok"] is False
    assert "Unsafe source or output path." not in result["message"]
    assert "Source path not found or not a directory." in result["message"]


def test_excludes_git_aegis_node_modules_and_cache_dirs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / ".git").mkdir()
    (source / ".git" / "config").write_text("x\n", encoding="utf-8")
    (source / ".aegis").mkdir()
    (source / ".aegis" / "runs.json").write_text("x\n", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "x.js").write_text("x\n", encoding="utf-8")
    (source / ".pytest_cache").mkdir()
    (source / ".pytest_cache" / "v").write_text("x\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "path: src/main.py" in text
    assert ".git/config" not in text
    assert ".aegis/runs.json" not in text
    assert "node_modules/x.js" not in text
    assert ".pytest_cache/v" not in text


def test_excludes_binary_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    (source / "src" / "image.bin").write_bytes(b"\x00\x01\x02")
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "path: src/main.py" in text
    assert "path: src/image.bin" not in text


def test_excludes_large_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    (source / "src" / "big.txt").write_text("a" * (101 * 1024), encoding="utf-8")
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "path: src/main.py" in text
    assert "path: src/big.txt" not in text


def test_exported_profile_paths_are_relative(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "path: src/main.py" in text
    assert "path: /" not in text
    assert "path: .." not in text
    assert "path: C:\\" not in text


def test_unsafe_internal_entries_are_skipped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    # Symlink that escapes source root should be skipped when supported.
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    link = source / "src"
    link.mkdir()
    escaped = link / "escaped.txt"
    try:
        escaped.symlink_to(outside)
    except Exception:
        return
    output = tmp_path / "profile.yml"
    result = export_scaffold_profile(Path("repo"), Path("profile.yml"))
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "escaped.txt" not in text


def test_output_inside_source_not_included(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    output = source / "profile.yml"
    output.write_text("old\n", encoding="utf-8")
    result = export_scaffold_profile(source, output)
    assert result["ok"] is True
    text = output.read_text(encoding="utf-8")
    assert "path: profile.yml" not in text
    skipped = result.get("skipped", [])
    assert any(str(item).startswith("output_profile:profile.yml") for item in skipped)


def test_generated_profile_works_with_create_from(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "repo"
    source.mkdir()
    (source / "README.md").write_text("# Demo\n", encoding="utf-8")
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("print('x')\n", encoding="utf-8")
    assert export_scaffold_profile(Path("repo"), Path("profile.yml"))["ok"] is True
    exit_code = cli.main(["create", "--from", "profile.yml", "--target", "new-project", "--confirm"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Scaffold created." in out
    assert (tmp_path / "new-project" / "README.md").exists()
    assert (tmp_path / "new-project" / "src" / "main.py").exists()
