from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aegis_code.operations.registry import get_operation


@dataclass(slots=True)
class BatchStep:
    operation: str
    target_file: str
    task: str
    anchor: str | None = None
    symbol: str | None = None
    destination_path: str | None = None


@dataclass(slots=True)
class BatchDefinition:
    version: int
    operations: list[BatchStep]
    stop_on_first_failure: bool = True


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def validate_batch_definition(data: dict[str, Any]) -> BatchDefinition:
    if not isinstance(data, dict):
        raise ValueError("batch definition must be a JSON object.")
    version = data.get("version")
    if version != 1:
        raise ValueError("batch definition version must be 1.")
    operations = data.get("operations")
    if not isinstance(operations, list) or not operations:
        raise ValueError("batch definition requires a non-empty operations list.")
    options = data.get("options", {})
    if options is None:
        options = {}
    if not isinstance(options, dict):
        raise ValueError("batch definition options must be an object when provided.")
    stop_on_first_failure = options.get("stop_on_first_failure", True)
    if not isinstance(stop_on_first_failure, bool):
        raise ValueError("batch option stop_on_first_failure must be a boolean.")
    normalized_steps: list[BatchStep] = []
    for idx, raw in enumerate(operations, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"batch operation step {idx} must be an object.")
        operation = _clean_text(raw.get("operation")).lower()
        if not operation:
            raise ValueError(f"batch operation step {idx} is missing required field: operation.")
        if operation == "batch":
            raise ValueError(f"batch operation step {idx} cannot use nested batch operation.")
        operation_definition = get_operation(operation)
        if operation_definition is None:
            raise ValueError(f"batch operation step {idx} uses unsupported operation: {operation}.")
        target_file = _clean_text(raw.get("target_file"))
        if not target_file:
            raise ValueError(f"batch operation step {idx} is missing required field: target_file.")
        task = _clean_text(raw.get("task"))
        if not task:
            raise ValueError(f"batch operation step {idx} requires a non-empty task.")
        anchor = _clean_text(raw.get("anchor")) or None
        symbol = _clean_text(raw.get("symbol")) or None
        destination_path = _clean_text(raw.get("destination_path")) or None
        if operation_definition.requires_anchor and not anchor:
            raise ValueError(f"batch operation step {idx} operation {operation} requires anchor.")
        if operation_definition.requires_symbol and not symbol:
            raise ValueError(f"batch operation step {idx} operation {operation} requires symbol.")
        if operation_definition.requires_destination_path and not destination_path:
            raise ValueError(f"batch operation step {idx} operation {operation} requires destination_path.")
        normalized_steps.append(
            BatchStep(
                operation=operation,
                target_file=target_file,
                task=task,
                anchor=anchor,
                symbol=symbol,
                destination_path=destination_path,
            )
        )
    return BatchDefinition(
        version=1,
        operations=normalized_steps,
        stop_on_first_failure=bool(stop_on_first_failure),
    )


def load_batch_definition(path: Path) -> BatchDefinition:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise ValueError(f"failed to read batch file: {path}") from exc
    try:
        data = json.loads(raw)
    except Exception as exc:
        raise ValueError("batch file is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise ValueError("batch definition root must be a JSON object.")
    return validate_batch_definition(data)

