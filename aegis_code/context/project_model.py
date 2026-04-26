from __future__ import annotations

from pathlib import Path

from aegis_code.config import project_paths


def load_project_model(cwd: Path | None = None) -> str:
    path = project_paths(cwd)["project_model_path"]
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()
