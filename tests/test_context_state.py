from __future__ import annotations

from pathlib import Path

from aegis_code import cli
from aegis_code.context_state import load_runtime_context


def test_context_refresh_creates_context_files(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n\nProject description.\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture.md").write_text("# Architecture\n\nLayered system.\n", encoding="utf-8")
    (tmp_path / "docs" / "constraints.md").write_text("# Constraints\n\nSafety rules.\n", encoding="utf-8")

    exit_code = cli.main(["context", "refresh"])
    assert exit_code == 0
    assert (tmp_path / ".aegis" / "context" / "project_summary.md").exists()
    assert (tmp_path / ".aegis" / "context" / "architecture.md").exists()
    assert (tmp_path / ".aegis" / "context" / "constraints.md").exists()


def test_context_refresh_routes_docs_by_filename(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "system-overview.md").write_text("System overview line.\n", encoding="utf-8")
    (tmp_path / "docs" / "safety-rules.md").write_text("Safety line.\n", encoding="utf-8")
    (tmp_path / "docs" / "notes.md").write_text("General note.\n", encoding="utf-8")
    exit_code = cli.main(["context", "refresh"])
    assert exit_code == 0
    arch = (tmp_path / ".aegis" / "context" / "architecture.md").read_text(encoding="utf-8")
    con = (tmp_path / ".aegis" / "context" / "constraints.md").read_text(encoding="utf-8")
    summary = (tmp_path / ".aegis" / "context" / "project_summary.md").read_text(encoding="utf-8")
    assert "docs/system-overview.md" in arch
    assert "docs/safety-rules.md" in con
    assert "- Additional doc: docs/notes.md" in summary


def test_context_refresh_skips_oversized_and_non_markdown_docs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "requirements.md").write_text("ok\n", encoding="utf-8")
    (tmp_path / "docs" / "design.txt").write_text("should skip\n", encoding="utf-8")
    large = tmp_path / "docs" / "architecture-large.md"
    large.write_text("a" * (101 * 1024), encoding="utf-8")
    exit_code = cli.main(["context", "refresh"])
    assert exit_code == 0
    arch = (tmp_path / ".aegis" / "context" / "architecture.md").read_text(encoding="utf-8")
    con = (tmp_path / ".aegis" / "context" / "constraints.md").read_text(encoding="utf-8")
    assert "architecture-large.md" not in arch
    assert "design.txt" not in arch
    assert "docs/requirements.md" in con


def test_context_show_missing_reports_clear_message(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["context", "show"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "No project context found. Run `aegis-code context refresh`." in out


def test_context_show_existing_reports_paths(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    cli.main(["context", "refresh"])
    exit_code = cli.main(["context", "show"])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Project context:" in out
    assert "project_summary.md" in out
    assert "architecture.md" in out
    assert "constraints.md" in out


def test_context_commands_do_not_call_runtime(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    monkeypatch.setattr("aegis_code.cli.run_task", lambda **_: (_ for _ in ()).throw(AssertionError("no runtime")))
    assert cli.main(["context", "refresh"]) == 0
    assert cli.main(["context", "show"]) == 0


def test_context_refresh_writes_only_under_aegis_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    cli.main(["context", "refresh"])
    expected = {
        str((tmp_path / ".aegis" / "context" / "project_summary.md").resolve()),
        str((tmp_path / ".aegis" / "context" / "architecture.md").resolve()),
        str((tmp_path / ".aegis" / "context" / "constraints.md").resolve()),
    }
    actual = {
        str(path.resolve())
        for path in (tmp_path / ".aegis" / "context").glob("*.md")
    }
    assert actual == expected


def test_context_missing_subcommand_prints_usage(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = cli.main(["context"])
    out = capsys.readouterr().out
    assert exit_code == 1
    assert "aegis-code context" in out


def test_load_runtime_context_unavailable_when_missing(tmp_path: Path) -> None:
    result = load_runtime_context(cwd=tmp_path)
    assert result["available"] is False
    assert result["files"] == {}
    assert result["included_paths"] == []
    assert result["total_chars"] == 0


def test_load_runtime_context_reads_files_and_tracks_paths(tmp_path: Path) -> None:
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("summary\n", encoding="utf-8")
    (context_dir / "constraints.md").write_text("constraints\n", encoding="utf-8")
    (context_dir / "architecture.md").write_text("architecture\n", encoding="utf-8")
    result = load_runtime_context(cwd=tmp_path)
    assert result["available"] is True
    assert ".aegis/context/project_summary.md" in result["included_paths"]
    assert ".aegis/context/constraints.md" in result["included_paths"]
    assert ".aegis/context/architecture.md" in result["included_paths"]
    assert result["total_chars"] > 0


def test_load_runtime_context_truncates_to_max_chars(tmp_path: Path) -> None:
    context_dir = tmp_path / ".aegis" / "context"
    context_dir.mkdir(parents=True, exist_ok=True)
    (context_dir / "project_summary.md").write_text("x" * 200, encoding="utf-8")
    result = load_runtime_context(cwd=tmp_path, max_chars=80)
    assert result["available"] is True
    assert result["total_chars"] <= 80
    assert "[truncated for runtime context budget]" in result["files"]["project_summary"]
