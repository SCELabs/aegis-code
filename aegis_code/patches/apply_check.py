from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.patches.diff_inspector import inspect_diff


def check_patch_file(path: Path, cwd: Path | None = None) -> dict[str, Any]:
    diff_text = path.read_text(encoding="utf-8")
    result = inspect_diff(diff_text, cwd=cwd)
    result["path"] = str(path)
    result["applied"] = False
    return result

