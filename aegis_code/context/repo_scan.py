from __future__ import annotations

from pathlib import Path

from aegis_code.models import RepoScanSummary

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".aegis",
}


def scan_repo(cwd: Path | None = None) -> RepoScanSummary:
    root = cwd or Path.cwd()
    file_count = 0
    top_level_dirs: list[str] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if child.name in IGNORED_DIRS:
            continue
        if child.is_dir():
            top_level_dirs.append(child.name)

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        file_count += 1

    return RepoScanSummary(file_count=file_count, top_level_directories=top_level_dirs)
