from __future__ import annotations

from difflib import unified_diff
from pathlib import Path, PurePosixPath
from typing import Any

from aegis_code.patches.apply_check import check_patch_text
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.diff_normalizer import normalize_unified_diff


def _normalize_patch_path(path_text: str) -> str:
    value = str(path_text or "").strip().replace("\\", "/")
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return str(PurePosixPath(value))


def _extract_target_path(diff_text: str) -> str | None:
    for line in str(diff_text or "").splitlines():
        if not line.startswith("+++ "):
            continue
        raw = line[4:].strip()
        if raw == "/dev/null":
            return None
        return _normalize_patch_path(raw)
    return None


def _extract_new_side_content(diff_text: str) -> str:
    out: list[str] = []
    for line in str(diff_text or "").splitlines():
        if not line:
            continue
        prefix = line[:1]
        if prefix in {" ", "+"} and not line.startswith("+++ "):
            out.append(line[1:])
    if not out:
        return ""
    return "\n".join(out) + "\n"


def _split_file_blocks(diff_text: str) -> list[list[str]]:
    lines = str(diff_text or "").splitlines()
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.startswith("diff --git "):
            if current:
                blocks.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_block_paths(block: list[str]) -> tuple[str | None, str | None]:
    old_path: str | None = None
    new_path: str | None = None
    for line in block:
        if line.startswith("--- "):
            raw = line[4:].strip()
            old_path = None if raw == "/dev/null" else _normalize_patch_path(raw)
        elif line.startswith("+++ "):
            raw = line[4:].strip()
            new_path = None if raw == "/dev/null" else _normalize_patch_path(raw)
    return old_path, new_path


def _extract_block_intended_content(block: list[str], *, is_new_file: bool) -> str:
    out: list[str] = []
    in_hunk = False
    for line in block:
        if line.startswith("@@ "):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("\\ No newline"):
            continue
        if line.startswith("diff --git "):
            break
        if line.startswith("+++ ") or line.startswith("--- "):
            continue
        if line.startswith("+"):
            out.append(line[1:])
            continue
        if line.startswith(" "):
            out.append(line[1:])
            continue
        if line.startswith("-"):
            if is_new_file:
                continue
            continue
    if not out:
        return ""
    return "\n".join(out) + "\n"


def _is_allowed_path(target: str) -> bool:
    if target.startswith("src/") or target.startswith("tests/"):
        return True
    if target == "README.md":
        return True
    if "/" not in target and target.endswith(".py"):
        return True
    return False


def _is_known_entrypoint(target: str) -> bool:
    return target in {"src/main.py", "main.py", "cli.py", "app.py"}


def _files_from_plan(patch_plan: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in patch_plan.get("proposed_changes", []) if isinstance(patch_plan, dict) else []:
        if isinstance(item, dict):
            path = str(item.get("file", "")).strip().replace("\\", "/")
            if path:
                out.add(path)
    return out


def _files_from_context(context: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in context.get("files", []) if isinstance(context, dict) else []:
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip().replace("\\", "/")
            if path:
                out.add(path)
    return out


def repair_malformed_diff(
    diff_text: str,
    cwd: Path,
    task: str,
    patch_plan: dict,
    context: dict,
) -> dict[str, Any]:
    _ = task
    _ = context
    source = str(diff_text or "")
    inspection = inspect_diff(source, cwd=cwd)
    errors = [str(item) for item in inspection.get("errors", [])]
    task_type = str((patch_plan or {}).get("task_type", "")).strip().lower()
    files = inspection.get("files", [])
    warnings = [str(item) for item in inspection.get("warnings", [])]

    blocks = _split_file_blocks(source)
    raw_repair_file_count = len(blocks)
    deduped_by_target: dict[str, list[str]] = {}
    for block in blocks:
        old_path, new_path = _parse_block_paths(block)
        target = new_path or old_path
        if target:
            deduped_by_target[target] = block
    repair_targets = sorted(deduped_by_target.keys())
    repair_file_count = len(repair_targets)

    if inspection.get("valid", False):
        return {
            "applied": False,
            "status": "skipped",
            "reason": "already_valid",
            "diff": source,
            "error": None,
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }
    if "hunk_count_mismatch" not in errors:
        return {
            "applied": False,
            "status": "skipped",
            "reason": "no_hunk_count_mismatch",
            "diff": source,
            "error": None,
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }
    if not isinstance(files, list) or not files:
        return {
            "applied": False,
            "status": "failed",
            "reason": "parse_failed",
            "diff": source,
            "error": "parse_failed",
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }
    severe_prefixes = ("unsafe_absolute_path", "unsafe_parent_traversal", "internal_or_generated_path")
    if any(w.startswith(severe_prefixes) for w in warnings):
        return {"applied": False, "status": "skipped", "reason": "unsafe_or_internal_target", "diff": source, "error": None}

    if task_type == "implementation_with_tests":
        if repair_file_count < 2 or repair_file_count > 3:
            return {
                "applied": False,
                "status": "skipped",
                "reason": "file_count_out_of_scope",
                "diff": source,
                "error": None,
                "repair_file_count": repair_file_count,
                "repair_targets": repair_targets,
                "raw_repair_file_count": raw_repair_file_count,
            }
    elif repair_file_count != 1:
        return {
            "applied": False,
            "status": "skipped",
            "reason": "file_count_out_of_scope",
            "diff": source,
            "error": None,
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }

    plan_files = _files_from_plan(patch_plan)
    context_files = _files_from_context(context)
    repaired_chunks: list[str] = []

    for target in repair_targets:
        block = deduped_by_target[target]
        old_path, new_path = _parse_block_paths(block)
        target = new_path or old_path
        if not target:
            return {
                "applied": False,
                "status": "failed",
                "reason": "missing_target_path",
                "diff": source,
                "error": "missing_target_path",
                "repair_file_count": repair_file_count,
                "repair_targets": repair_targets,
                "raw_repair_file_count": raw_repair_file_count,
            }
        if not _is_allowed_path(target):
            return {
                "applied": False,
                "status": "skipped",
                "reason": "target_not_allowed_path",
                "diff": source,
                "error": None,
                "repair_file_count": repair_file_count,
                "repair_targets": repair_targets,
                "raw_repair_file_count": raw_repair_file_count,
            }

        if task_type == "test_generation":
            if not target.startswith("tests/"):
                return {
                    "applied": False,
                    "status": "skipped",
                    "reason": "target_not_test_file",
                    "diff": source,
                    "error": None,
                    "repair_file_count": repair_file_count,
                    "repair_targets": repair_targets,
                    "raw_repair_file_count": raw_repair_file_count,
                }
        elif task_type == "implementation_with_tests":
            if target not in plan_files:
                return {
                    "applied": False,
                    "status": "skipped",
                    "reason": "target_not_in_plan",
                    "diff": source,
                    "error": None,
                    "repair_file_count": repair_file_count,
                    "repair_targets": repair_targets,
                    "raw_repair_file_count": raw_repair_file_count,
                }
        elif task_type not in {"general", ""}:
            return {
                "applied": False,
                "status": "skipped",
                "reason": "unsupported_task_type",
                "diff": source,
                "error": None,
                "repair_file_count": repair_file_count,
                "repair_targets": repair_targets,
                "raw_repair_file_count": raw_repair_file_count,
            }
        else:
            if target not in plan_files and target not in context_files and not _is_known_entrypoint(target):
                return {
                    "applied": False,
                    "status": "skipped",
                    "reason": "target_not_in_plan_or_context",
                    "diff": source,
                    "error": None,
                    "repair_file_count": repair_file_count,
                    "repair_targets": repair_targets,
                    "raw_repair_file_count": raw_repair_file_count,
                }

        target_file = cwd / target
        is_new_file = old_path is None or (not target_file.exists() and old_path is not None and task_type == "implementation_with_tests")
        if not target_file.exists() and old_path is not None and task_type != "implementation_with_tests":
            return {
                "applied": False,
                "status": "skipped",
                "reason": "target_missing_for_repair",
                "diff": source,
                "error": None,
                "repair_file_count": repair_file_count,
                "repair_targets": repair_targets,
                "raw_repair_file_count": raw_repair_file_count,
            }
        current = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        intended = _extract_block_intended_content(block, is_new_file=is_new_file)
        file_diff_lines = list(
            unified_diff(
                current.splitlines(),
                intended.splitlines(),
                fromfile=f"a/{target}",
                tofile=f"b/{target}",
                lineterm="",
            )
        )
        if is_new_file:
            file_diff_lines = ["/dev/null" if line == f"--- a/{target}" else line for line in file_diff_lines]
        if not file_diff_lines:
            continue
        repaired_chunks.append(f"diff --git a/{target} b/{target}\n" + "".join(line + "\n" for line in file_diff_lines))

    repaired = normalize_unified_diff("".join(repaired_chunks))

    repaired_inspection = inspect_diff(repaired, cwd=cwd)
    repaired_check = check_patch_text(repaired, cwd=cwd)
    if bool(repaired_inspection.get("valid", False)) and not bool(repaired_check.get("apply_blocked", False)):
        return {
            "applied": True,
            "status": "repaired",
            "reason": "hunk_count_repaired",
            "diff": repaired,
            "error": None,
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }
    if bool(repaired_check.get("apply_blocked", False)):
        return {
            "applied": False,
            "status": "failed",
            "reason": "check_blocked",
            "diff": source,
            "error": str((repaired_check.get("errors") or ["check_blocked"])[0]),
            "repair_file_count": repair_file_count,
            "repair_targets": repair_targets,
            "raw_repair_file_count": raw_repair_file_count,
        }
    repaired_errors = [str(item) for item in repaired_inspection.get("errors", [])]
    return {
        "applied": False,
        "status": "failed",
        "reason": "validation_failed",
        "diff": source,
        "error": repaired_errors[0] if repaired_errors else "validation_failed",
        "repair_file_count": repair_file_count,
        "repair_targets": repair_targets,
        "raw_repair_file_count": raw_repair_file_count,
    }
