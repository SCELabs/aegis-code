from __future__ import annotations

from enum import Enum
from typing import Literal, TypeAlias

from aegis_code.api.errors import AegisPatchError


PatchOperationValue: TypeAlias = Literal[
    "append",
    "create-file",
    "insert-after",
    "insert-before",
    "replace-block",
    "delete-block",
    "replace-file",
    "delete-file",
    "replace-symbol",
    "delete-symbol",
    "rename-file",
    "move-file",
    "batch",
]


class PatchOperation(str, Enum):
    APPEND = "append"
    CREATE_FILE = "create-file"
    INSERT_AFTER = "insert-after"
    INSERT_BEFORE = "insert-before"
    REPLACE_BLOCK = "replace-block"
    DELETE_BLOCK = "delete-block"
    REPLACE_FILE = "replace-file"
    DELETE_FILE = "delete-file"
    REPLACE_SYMBOL = "replace-symbol"
    DELETE_SYMBOL = "delete-symbol"
    RENAME_FILE = "rename-file"
    MOVE_FILE = "move-file"
    BATCH = "batch"


_SUPPORTED_PATCH_OPERATIONS = {item.value for item in PatchOperation}


def normalize_operation(operation: PatchOperation | PatchOperationValue | str | None) -> str | None:
    if operation is None:
        return None
    if isinstance(operation, PatchOperation):
        value = str(operation.value).strip().lower()
    else:
        value = str(operation).strip().lower()
    if not value:
        return None
    if value not in _SUPPORTED_PATCH_OPERATIONS:
        supported = ", ".join(sorted(_SUPPORTED_PATCH_OPERATIONS))
        raise AegisPatchError(f"Unsupported patch operation: {value}. Supported operations: {supported}")
    return value
