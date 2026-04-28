from __future__ import annotations

from pathlib import Path

from aegis_code.config import project_paths


def write_latest_diff(diff: str, cwd: Path | None = None) -> Path:
    paths = project_paths(cwd)
    paths["runs_dir"].mkdir(parents=True, exist_ok=True)
    output = paths["latest_diff"]
    output.write_text(diff, encoding="utf-8")
    return output

