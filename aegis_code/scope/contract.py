from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ScopeContract:
    source: str
    allowed_targets: list[str]
    max_files: int
    allow_new_files: bool
    allowed_operations: list[str]
    missing_targets: list[str]
    block_reason: str | None


def _normalize_rel(path_text: str, cwd: Path) -> str:
    raw = str(path_text or "").strip().replace("\\", "/")
    if not raw:
        return ""
    p = Path(raw)
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(cwd.resolve())
            return rel.as_posix()
        except Exception:
            return p.as_posix()
    return p.as_posix().lstrip("./")


def build_scope_contract_from_cli(
    files: list[str],
    allow_create: bool,
    max_files: int | None,
    cwd: Path,
) -> ScopeContract:
    normalized: list[str] = []
    for value in files:
        rel = _normalize_rel(value, cwd)
        if rel and rel not in normalized:
            normalized.append(rel)
    missing_targets = [path for path in normalized if not (cwd / path).exists()]
    resolved_max = int(max_files) if isinstance(max_files, int) and max_files > 0 else len(normalized)
    allow_new_files = bool(allow_create)
    allowed_operations = ["create", "replace"] if allow_new_files else ["replace"]
    block_reason = "requested_target_missing" if missing_targets and not allow_new_files else None
    return ScopeContract(
        source="cli_explicit",
        allowed_targets=normalized,
        max_files=max(0, resolved_max),
        allow_new_files=allow_new_files,
        allowed_operations=allowed_operations,
        missing_targets=missing_targets,
        block_reason=block_reason,
    )
