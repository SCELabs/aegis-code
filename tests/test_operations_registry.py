from __future__ import annotations

from aegis_code.operations.registry import (
    OPERATIONS,
    get_operation,
    is_supported_operation,
    list_operation_names,
    list_provider_free_operations,
    list_provider_required_operations,
)


def test_operation_registry_contains_all_supported_operations() -> None:
    assert list_operation_names() == [
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
    assert set(OPERATIONS.keys()) == set(list_operation_names())


def test_operation_registry_metadata_flags_are_correct() -> None:
    assert get_operation("append") is not None
    assert get_operation("append").provider_required is True  # type: ignore[union-attr]
    assert get_operation("append").requires_target_file is True  # type: ignore[union-attr]
    assert get_operation("append").requires_anchor is False  # type: ignore[union-attr]
    assert get_operation("append").requires_symbol is False  # type: ignore[union-attr]
    assert get_operation("append").requires_destination_path is False  # type: ignore[union-attr]

    assert get_operation("create-file").allows_new_files is True  # type: ignore[union-attr]
    assert get_operation("create-file").allows_deletions is False  # type: ignore[union-attr]

    assert get_operation("insert-after").requires_anchor is True  # type: ignore[union-attr]
    assert get_operation("insert-before").requires_anchor is True  # type: ignore[union-attr]
    assert get_operation("replace-block").requires_anchor is True  # type: ignore[union-attr]
    assert get_operation("delete-block").provider_required is False  # type: ignore[union-attr]

    assert get_operation("replace-symbol").requires_symbol is True  # type: ignore[union-attr]
    assert get_operation("replace-symbol").provider_required is True  # type: ignore[union-attr]
    assert get_operation("delete-symbol").requires_symbol is True  # type: ignore[union-attr]
    assert get_operation("delete-symbol").provider_required is False  # type: ignore[union-attr]

    assert get_operation("rename-file").requires_destination_path is True  # type: ignore[union-attr]
    assert get_operation("rename-file").allows_new_files is True  # type: ignore[union-attr]
    assert get_operation("move-file").requires_destination_path is True  # type: ignore[union-attr]
    assert get_operation("move-file").allows_new_files is True  # type: ignore[union-attr]
    assert get_operation("batch").category == "composite"  # type: ignore[union-attr]
    assert get_operation("batch").provider_required is False  # type: ignore[union-attr]


def test_operation_registry_helper_functions() -> None:
    assert is_supported_operation("append") is True
    assert is_supported_operation("APPEND") is True
    assert is_supported_operation("unknown-op") is False
    assert get_operation("unknown-op") is None

    assert list_provider_required_operations() == [
        "append",
        "create-file",
        "insert-after",
        "insert-before",
        "replace-block",
        "replace-file",
        "replace-symbol",
    ]
    assert list_provider_free_operations() == [
        "delete-block",
        "delete-file",
        "delete-symbol",
        "rename-file",
        "move-file",
        "batch",
    ]
