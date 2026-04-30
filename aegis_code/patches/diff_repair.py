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

    if inspection.get("valid", False):
        return {"applied": False, "status": "skipped", "reason": "already_valid", "diff": source, "error": None}
    if "hunk_count_mismatch" not in errors:
        return {"applied": False, "status": "skipped", "reason": "not_hunk_count_mismatch", "diff": source, "error": None}
    if not isinstance(files, list) or len(files) != 1:
        return {"applied": False, "status": "skipped", "reason": "not_single_file_target", "diff": source, "error": None}
    severe_prefixes = ("unsafe_absolute_path", "unsafe_parent_traversal", "internal_or_generated_path")
    if any(w.startswith(severe_prefixes) for w in warnings):
        return {"applied": False, "status": "skipped", "reason": "unsafe_or_internal_target", "diff": source, "error": None}

    target = _extract_target_path(source)
    if not target:
        return {"applied": False, "status": "failed", "reason": "missing_target_path", "diff": source, "error": "missing_target_path"}
    if not _is_allowed_path(target):
        return {"applied": False, "status": "skipped", "reason": "target_not_allowed_path", "diff": source, "error": None}

    if task_type == "test_generation":
        if not target.startswith("tests/"):
            return {"applied": False, "status": "skipped", "reason": "target_not_test_file", "diff": source, "error": None}
    else:
        plan_files = _files_from_plan(patch_plan)
        context_files = _files_from_context(context)
        if target not in plan_files and target not in context_files and not _is_known_entrypoint(target):
            return {"applied": False, "status": "skipped", "reason": "target_not_in_plan_or_context", "diff": source, "error": None}

    target_file = cwd / target
    old_path = files[0].get("old_path") if isinstance(files[0], dict) else None
    if not target_file.exists() and old_path is not None:
        return {"applied": False, "status": "skipped", "reason": "target_missing_for_repair", "diff": source, "error": None}
    current = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
    intended = _extract_new_side_content(source)
    repaired = "".join(
        line + "\n"
        for line in unified_diff(
            current.splitlines(),
            intended.splitlines(),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
            lineterm="",
        )
    )
    repaired = normalize_unified_diff(repaired)

    repaired_inspection = inspect_diff(repaired, cwd=cwd)
    repaired_check = check_patch_text(repaired, cwd=cwd)
    if bool(repaired_inspection.get("valid", False)) and not bool(repaired_check.get("apply_blocked", False)):
        return {"applied": True, "status": "repaired", "reason": "hunk_count_repaired", "diff": repaired, "error": None}
    repaired_errors = [str(item) for item in repaired_inspection.get("errors", [])]
    return {
        "applied": False,
        "status": "failed",
        "reason": "repaired_diff_invalid",
        "diff": source,
        "error": repaired_errors[0] if repaired_errors else "repaired_diff_invalid",
    }
