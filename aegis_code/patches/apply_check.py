from __future__ import annotations

from pathlib import Path
from typing import Any

from aegis_code.patches.diff_inspector import inspect_diff


def check_patch_text(diff_text: str, cwd: Path | None = None) -> dict[str, Any]:
    result = inspect_diff(diff_text, cwd=cwd)
    warnings = result.get("warnings", [])
    blockers = []
    if not bool(result.get("valid", False)) or bool(result.get("errors", [])):
        blockers.append("invalid_diff")
    severe_prefixes = ("unsafe_absolute_path", "unsafe_parent_traversal", "internal_or_generated_path")
    if any(str(item).startswith(severe_prefixes) for item in warnings):
        blockers.append("unsafe_paths")
    if "binary_diff_detected" in warnings:
        blockers.append("binary_diff_unsupported")
    result["path"] = "<inline>"
    result["applied"] = False
    result["apply_blocked"] = bool(blockers)
    result["apply_block_reasons"] = blockers
    return result


def check_patch_file(path: Path, cwd: Path | None = None) -> dict[str, Any]:
    diff_text = path.read_text(encoding="utf-8")
    result = check_patch_text(diff_text, cwd=cwd)
    result["path"] = str(path)
    return result


def format_apply_check_result(result: dict[str, Any]) -> str:
    summary = result.get("summary", {})
    lines = [
        f"Patch check: {result.get('path')}",
        f"Valid: {result.get('valid', False)}",
        f"Files: {summary.get('file_count', 0)}",
        f"Hunks: {summary.get('hunk_count', 0)}",
        f"Additions: {summary.get('additions', 0)}",
        f"Deletions: {summary.get('deletions', 0)}",
        "Warnings:",
    ]
    warnings = result.get("warnings", [])
    if warnings:
        lines.extend(f"- {item}" for item in warnings)
    else:
        lines.append("- none")
    lines.append("Errors:")
    errors = result.get("errors", [])
    if errors:
        lines.extend(f"- {item}" for item in errors)
    else:
        lines.append("- none")
    lines.append(f"Apply blocked: {result.get('apply_blocked', False)}")
    blockers = result.get("apply_block_reasons", [])
    if blockers:
        lines.append("Apply block reasons:")
        lines.extend(f"- {item}" for item in blockers)
    lines.append(f"Applied: {result.get('applied', False)}")
    return "\n".join(lines)
