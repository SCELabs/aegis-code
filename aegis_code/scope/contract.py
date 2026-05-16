from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aegis_code.operations.registry import get_operation


@dataclass(slots=True)
class ScopeContract:
    source: str
    allowed_targets: list[str]
    max_files: int
    allow_new_files: bool
    allowed_operations: list[str]
    operation: str | None
    destination_path: str | None
    anchor: str | None
    symbol: str | None
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
    operation: str | None = None,
    destination_path: str | None = None,
    anchor: str | None = None,
    symbol: str | None = None,
) -> ScopeContract:
    normalized: list[str] = []
    for value in files:
        rel = _normalize_rel(value, cwd)
        if rel and rel not in normalized:
            normalized.append(rel)
    missing_targets = [path for path in normalized if not (cwd / path).exists()]
    resolved_max = int(max_files) if isinstance(max_files, int) and max_files > 0 else len(normalized)
    normalized_operation = str(operation or "").strip().lower()
    operation_definition = get_operation(normalized_operation) if normalized_operation else None
    normalized_destination = _normalize_rel(str(destination_path or ""), cwd) if str(destination_path or "").strip() else None
    normalized_anchor = str(anchor or "").strip() or None
    normalized_symbol = str(symbol or "").strip() or None
    if operation_definition is not None:
        allow_new_files = bool(operation_definition.allows_new_files)
        allowed_operations = [operation_definition.name]
    else:
        allow_new_files = bool(allow_create)
        allowed_operations = ["create", "replace"] if allow_new_files else ["replace"]
    block_reason: str | None = None
    if normalized_operation and operation_definition is None:
        block_reason = "operation_contract_invalid"
    requires_existing_source = bool(
        operation_definition is not None
        and operation_definition.requires_target_file
        and operation_definition.name != "create-file"
    )
    if missing_targets:
        if normalized_operation and block_reason is None:
            if requires_existing_source:
                block_reason = "requested_target_missing"
        elif not allow_new_files:
            block_reason = "requested_target_missing"
    return ScopeContract(
        source="cli_explicit",
        allowed_targets=normalized,
        max_files=max(0, resolved_max),
        allow_new_files=allow_new_files,
        allowed_operations=allowed_operations,
        operation=normalized_operation or None,
        destination_path=normalized_destination,
        anchor=normalized_anchor,
        symbol=normalized_symbol,
        missing_targets=missing_targets,
        block_reason=block_reason,
    )
