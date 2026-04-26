from __future__ import annotations

from pathlib import Path


def is_git_repo(cwd: Path | None = None) -> bool:
    root = cwd or Path.cwd()
    return (root / ".git").exists()
