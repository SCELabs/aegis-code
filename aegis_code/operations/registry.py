from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OperationDefinition:
    name: str
    category: str
    provider_required: bool
    requires_target_file: bool = False
    requires_anchor: bool = False
    requires_symbol: bool = False
    requires_destination_path: bool = False
    allows_new_files: bool = False
    allows_deletions: bool = False
    description: str = ""


OPERATIONS: dict[str, OperationDefinition] = {
    "append": OperationDefinition(
        name="append",
        category="content",
        provider_required=True,
        requires_target_file=True,
        description="Append content to the end of one explicit file.",
    ),
    "create-file": OperationDefinition(
        name="create-file",
        category="file",
        provider_required=True,
        requires_target_file=True,
        allows_new_files=True,
        description="Create one explicit new file with provider-generated content.",
    ),
    "insert-after": OperationDefinition(
        name="insert-after",
        category="content",
        provider_required=True,
        requires_target_file=True,
        requires_anchor=True,
        description="Insert provider-generated content after an exact anchor line.",
    ),
    "insert-before": OperationDefinition(
        name="insert-before",
        category="content",
        provider_required=True,
        requires_target_file=True,
        requires_anchor=True,
        description="Insert provider-generated content before an exact anchor line.",
    ),
    "replace-block": OperationDefinition(
        name="replace-block",
        category="content",
        provider_required=True,
        requires_target_file=True,
        requires_anchor=True,
        allows_deletions=True,
        description="Replace an exact block in one explicit target file.",
    ),
    "delete-block": OperationDefinition(
        name="delete-block",
        category="content",
        provider_required=False,
        requires_target_file=True,
        requires_anchor=True,
        allows_deletions=True,
        description="Delete an exact block from one explicit target file.",
    ),
    "replace-file": OperationDefinition(
        name="replace-file",
        category="file",
        provider_required=True,
        requires_target_file=True,
        allows_deletions=True,
        description="Rewrite one explicit existing file.",
    ),
    "delete-file": OperationDefinition(
        name="delete-file",
        category="file",
        provider_required=False,
        requires_target_file=True,
        allows_deletions=True,
        description="Delete one explicit existing file.",
    ),
    "replace-symbol": OperationDefinition(
        name="replace-symbol",
        category="symbol",
        provider_required=True,
        requires_target_file=True,
        requires_symbol=True,
        allows_deletions=True,
        description="Replace one uniquely resolved symbol in one explicit file.",
    ),
    "delete-symbol": OperationDefinition(
        name="delete-symbol",
        category="symbol",
        provider_required=False,
        requires_target_file=True,
        requires_symbol=True,
        allows_deletions=True,
        description="Delete one uniquely resolved symbol from one explicit file.",
    ),
    "rename-file": OperationDefinition(
        name="rename-file",
        category="file",
        provider_required=False,
        requires_target_file=True,
        requires_destination_path=True,
        allows_new_files=True,
        allows_deletions=True,
        description="Rename one explicit source file to a new destination path.",
    ),
    "move-file": OperationDefinition(
        name="move-file",
        category="file",
        provider_required=False,
        requires_target_file=True,
        requires_destination_path=True,
        allows_new_files=True,
        allows_deletions=True,
        description="Move one explicit source file to a new destination path.",
    ),
    "batch": OperationDefinition(
        name="batch",
        category="composite",
        provider_required=False,
        requires_target_file=False,
        description="Execute multiple controlled operations atomically.",
    ),
}


def get_operation(name: str | None) -> OperationDefinition | None:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return None
    return OPERATIONS.get(normalized)


def is_supported_operation(name: str | None) -> bool:
    return get_operation(name) is not None


def list_operation_names() -> list[str]:
    return list(OPERATIONS.keys())


def list_provider_required_operations() -> list[str]:
    return [name for name, definition in OPERATIONS.items() if definition.provider_required]


def list_provider_free_operations() -> list[str]:
    return [name for name, definition in OPERATIONS.items() if not definition.provider_required]
