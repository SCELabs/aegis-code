from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OperationContract:
    operation: str
    target_file: str | None
    anchor: str | None = None
    symbol: str | None = None
    allow_deletions: bool = False
    allow_new_file: bool = False
    max_changed_lines: int | None = None
    source: str = "unknown"


def normalize_operation_contract(
    *,
    operation: str,
    target_file: str | None,
    anchor: str | None = None,
    symbol: str | None = None,
    allow_deletions: bool = False,
    allow_new_file: bool = False,
    max_changed_lines: int | None = None,
    source: str = "unknown",
) -> OperationContract:
    normalized_operation = str(operation or "").strip().lower()
    normalized_target = str(target_file).strip() if target_file is not None else None
    normalized_anchor = str(anchor).strip() if anchor is not None else None
    normalized_symbol = str(symbol).strip() if symbol is not None else None
    normalized_source = str(source or "unknown").strip() or "unknown"
    return OperationContract(
        operation=normalized_operation,
        target_file=normalized_target,
        anchor=normalized_anchor,
        symbol=normalized_symbol,
        allow_deletions=bool(allow_deletions),
        allow_new_file=bool(allow_new_file),
        max_changed_lines=max_changed_lines,
        source=normalized_source,
    )

