from __future__ import annotations

from pathlib import Path

from aegis_code.config import project_paths


def write_latest_diff(diff: str, cwd: Path | None = None) -> Path:
    paths = project_paths(cwd)
    paths["runs_dir"].mkdir(parents=True, exist_ok=True)
    output = paths["latest_diff"]
    output.write_text(diff, encoding="utf-8")
    return output


def write_latest_invalid_diff(diff: str, cwd: Path | None = None) -> Path:
    paths = project_paths(cwd)
    paths["runs_dir"].mkdir(parents=True, exist_ok=True)
    output = paths["runs_dir"] / "latest.invalid.diff"
    output.write_text(diff, encoding="utf-8")
    return output


def remove_latest_diff(cwd: Path | None = None) -> None:
    latest = project_paths(cwd)["latest_diff"]
    if latest.exists():
        latest.unlink()
