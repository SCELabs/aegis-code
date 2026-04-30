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

    if inspection.get("valid", False):
        return {"applied": False, "status": "skipped", "reason": "already_valid", "diff": source, "error": None}
    if "hunk_count_mismatch" not in errors:
        return {"applied": False, "status": "skipped", "reason": "not_hunk_count_mismatch", "diff": source, "error": None}
    if task_type != "test_generation":
        return {"applied": False, "status": "skipped", "reason": "not_test_generation_task", "diff": source, "error": None}
    if not isinstance(files, list) or len(files) != 1:
        return {"applied": False, "status": "skipped", "reason": "not_single_file_target", "diff": source, "error": None}

    target = _extract_target_path(source)
    if not target:
        return {"applied": False, "status": "failed", "reason": "missing_target_path", "diff": source, "error": "missing_target_path"}
    if not target.startswith("tests/"):
        return {"applied": False, "status": "skipped", "reason": "target_not_test_file", "diff": source, "error": None}

    target_file = cwd / target
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
