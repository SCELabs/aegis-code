from __future__ import annotations

from pathlib import Path
from typing import Any


def _safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def _find_candidate_source(test_file: Path, cwd: Path) -> Path | None:
    parts = list(test_file.parts)
    if "tests" not in parts:
        return None

    test_index = parts.index("tests")
    suffix_parts = parts[test_index + 1 :]
    if not suffix_parts:
        return None

    test_name = suffix_parts[-1]
    if not test_name.startswith("test_") or not test_name.endswith(".py"):
        return None

    source_name = test_name[len("test_") :]
    mapped_parts = suffix_parts[:-1] + [source_name]
    candidates = [
        cwd / "aegis_code" / Path(*mapped_parts),
        cwd / Path(*mapped_parts),
        cwd / "src" / Path(*mapped_parts),
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def build_failure_context(failures: list[dict[str, Any]], cwd: Path) -> dict[str, list[dict[str, str]]]:
    files: list[dict[str, str]] = []
    seen: set[Path] = set()

    for failure in failures:
        raw_path = str(failure.get("file", "")).strip()
        if not raw_path:
            continue

        test_path = Path(raw_path)
        if not test_path.is_absolute():
            test_path = cwd / test_path
        test_path = test_path.resolve()

        if test_path.exists() and test_path.is_file() and test_path not in seen:
            seen.add(test_path)
            files.append(
                {
                    "path": _display_path(test_path, cwd),
                    "content": _safe_read_text(test_path),
                }
            )

        source_path = _find_candidate_source(test_path, cwd)
        if source_path and source_path not in seen:
            seen.add(source_path)
            files.append(
                {
                    "path": _display_path(source_path, cwd),
                    "content": _safe_read_text(source_path),
                }
            )

    return {"files": files}
