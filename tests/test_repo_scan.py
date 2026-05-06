from __future__ import annotations

from pathlib import Path

from aegis_code.context.repo_scan import MAX_REPO_MAP_CHARS, build_python_repo_map, scan_repo


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


def test_python_repo_map_extracts_symbols_and_tests(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "class Runner:\n    pass\n\ndef main():\n    return 1\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_app.py").write_text(
        "def test_top_level():\n    assert True\n\nclass TestApp:\n    def test_method(self):\n        assert True\n",
        encoding="utf-8",
    )
    repo_map = build_python_repo_map(tmp_path)
    assert repo_map["source_files"][0]["path"] == "src/app.py"
    assert "main" in repo_map["source_files"][0]["functions"]
    assert "Runner" in repo_map["source_files"][0]["classes"]
    assert repo_map["test_files"][0]["path"] == "tests/test_app.py"
    assert "test_top_level" in repo_map["test_files"][0]["tests"]
    assert "TestApp.test_method" in repo_map["test_files"][0]["tests"]


def test_python_repo_map_cli_hints_detect_main_and_sys_argv(tmp_path: Path) -> None:
    (tmp_path / "cli.py").write_text(
        "import argparse\nimport sys\n\ndef main():\n    parser = argparse.ArgumentParser()\n    _ = sys.argv\n\nif __name__ == \"__main__\":\n    main()\n",
        encoding="utf-8",
    )
    repo_map = build_python_repo_map(tmp_path)
    hints = repo_map["cli_hints"]
    assert "cli.py" in hints["main_guard_files"]
    assert "cli.py" in hints["main_function_files"]
    assert "cli.py" in hints["argparse_files"]
    assert "cli.py" in hints["sys_argv_files"]


def test_python_repo_map_stable_ordering(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("def z():\n    pass\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("def a():\n    pass\n", encoding="utf-8")
    first = build_python_repo_map(tmp_path)
    second = build_python_repo_map(tmp_path)
    assert first["source_files"] == second["source_files"]
    assert [item["path"] for item in first["source_files"]] == ["a.py", "z.py"]


def test_python_repo_map_is_capped_and_truncated(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    big_symbols = "\n".join(f"def fn_{idx:03d}():\n    return {idx}" for idx in range(200))
    for i in range(40):
        (tmp_path / "src" / f"m_{i:02d}.py").write_text(big_symbols + "\n", encoding="utf-8")
    repo_map = build_python_repo_map(tmp_path)
    assert len(repo_map["source_files"]) <= repo_map["limits"]["max_source_files"]
    assert repo_map["char_count"] <= MAX_REPO_MAP_CHARS
    assert isinstance(repo_map["rendered"], str) and repo_map["rendered"]
