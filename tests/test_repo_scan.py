from __future__ import annotations

from pathlib import Path

from aegis_code.context.repo_scan import scan_repo


def test_scan_repo_ignores_pytest_cache_and_egg_info(tmp_path: Path) -> None:
    (tmp_path / "aegis_code").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / "pkg.egg-info").mkdir()

    (tmp_path / "aegis_code" / "x.py").write_text("x=1\n", encoding="utf-8")
    (tmp_path / ".pytest_cache" / "cached").write_text("noise\n", encoding="utf-8")
    (tmp_path / "pkg.egg-info" / "PKG-INFO").write_text("meta\n", encoding="utf-8")

    summary = scan_repo(tmp_path)
    assert ".pytest_cache" not in summary.top_level_directories
    assert "pkg.egg-info" not in summary.top_level_directories
    assert summary.file_count == 1

