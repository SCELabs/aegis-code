from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff
from pathlib import Path
import shutil
import tempfile
from typing import Any

from aegis_code.batch_schema import BatchDefinition
from aegis_code.operations import normalize_operation_contract
from aegis_code.operations.registry import get_operation
from aegis_code.patches.diff_parser import parse_apply_diff
from aegis_code.providers import generate_structured_edits, generate_text
from aegis_code.providers.prompts import (
    build_create_file_prompt,
    build_insert_after_prompt,
    build_insert_before_prompt,
    build_replace_block_prompt,
    build_replace_file_prompt,
    build_replace_symbol_prompt,
)
from aegis_code.runtime_components.operation_stage import run_operation_stage


@dataclass(slots=True)
class BatchExecutionResult:
    success: bool
    diff_text: str
    total_steps: int = 0
    completed_steps: int = 0
    step_results: list[dict[str, Any]] = field(default_factory=list)
    failed_step_index: int | None = None
    error: str | None = None


def _ensure_within_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _apply_hunks(source: str, hunks: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    src_lines = source.splitlines()
    out: list[str] = []
    src_idx = 0
    for hunk in hunks:
        old_start = int(hunk["old_start"])
        target_idx = 0 if old_start == 0 else old_start - 1
        if target_idx < src_idx or target_idx > len(src_lines):
            return None, "context_mismatch"
        out.extend(src_lines[src_idx:target_idx])
        src_idx = target_idx
        for kind, text in hunk["lines"]:
            if kind == " ":
                if src_idx >= len(src_lines) or src_lines[src_idx] != text:
                    return None, "context_mismatch"
                out.append(src_lines[src_idx])
                src_idx += 1
            elif kind == "-":
                if src_idx >= len(src_lines) or src_lines[src_idx] != text:
                    return None, "context_mismatch"
                src_idx += 1
            elif kind == "+":
                out.append(text)
    out.extend(src_lines[src_idx:])
    if not out:
        return "", None
    return "\n".join(out) + ("\n" if source.endswith("\n") or not source else ""), None


def _apply_step_diff(*, diff_text: str, workspace_root: Path) -> tuple[bool, str | None, set[str]]:
    files, parse_errors = parse_apply_diff(diff_text)
    if parse_errors:
        return False, parse_errors[0], set()
    touched_paths: set[str] = set()
    for file_patch in files:
        old_path = file_patch.get("old_path")
        new_path = file_patch.get("new_path")
        if isinstance(old_path, str) and old_path.strip():
            touched_paths.add(str(old_path).replace("\\", "/"))
        if isinstance(new_path, str) and new_path.strip():
            touched_paths.add(str(new_path).replace("\\", "/"))

        if old_path is None and new_path is None:
            return False, "unsupported_new_or_delete_file", touched_paths

        if old_path is None and isinstance(new_path, str):
            target = (workspace_root / new_path).resolve()
            if not _ensure_within_root(target, workspace_root):
                return False, "path_outside_cwd", touched_paths
            if target.exists():
                return False, "target_already_exists", touched_paths
            updated, apply_error = _apply_hunks("", file_patch.get("hunks", []))
            if apply_error or updated is None:
                return False, apply_error or "context_mismatch", touched_paths
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(updated, encoding="utf-8")
            continue

        if isinstance(old_path, str) and new_path is None:
            target = (workspace_root / old_path).resolve()
            if not _ensure_within_root(target, workspace_root):
                return False, "path_outside_cwd", touched_paths
            if not target.exists() or not target.is_file():
                return False, "missing_target_file", touched_paths
            source = target.read_text(encoding="utf-8", errors="replace")
            updated, apply_error = _apply_hunks(source, file_patch.get("hunks", []))
            if apply_error or updated is None:
                return False, apply_error or "context_mismatch", touched_paths
            if updated.strip():
                return False, "unsupported_delete_file", touched_paths
            target.unlink()
            continue

        assert isinstance(old_path, str) and isinstance(new_path, str)
        source_path = (workspace_root / old_path).resolve()
        target_path = (workspace_root / new_path).resolve()
        if not _ensure_within_root(source_path, workspace_root) or not _ensure_within_root(target_path, workspace_root):
            return False, "path_outside_cwd", touched_paths
        if not source_path.exists() or not source_path.is_file():
            return False, "missing_target_file", touched_paths
        if source_path.resolve() != target_path.resolve() and target_path.exists():
            return False, "target_already_exists", touched_paths
        source = source_path.read_text(encoding="utf-8", errors="replace")
        updated, apply_error = _apply_hunks(source, file_patch.get("hunks", []))
        if apply_error or updated is None:
            return False, apply_error or "context_mismatch", touched_paths
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(updated, encoding="utf-8")
        if source_path.resolve() != target_path.resolve():
            source_path.unlink()
    return True, None, touched_paths


def _build_file_diff(*, relative_path: str, original_root: Path, updated_root: Path) -> str:
    original_path = (original_root / relative_path).resolve()
    updated_path = (updated_root / relative_path).resolve()
    original_exists = original_path.exists() and original_path.is_file()
    updated_exists = updated_path.exists() and updated_path.is_file()
    if original_exists and updated_exists:
        original_text = original_path.read_text(encoding="utf-8", errors="replace")
        updated_text = updated_path.read_text(encoding="utf-8", errors="replace")
        if original_text == updated_text:
            return ""
        body = list(
            unified_diff(
                original_text.splitlines(),
                updated_text.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        if not body:
            return ""
        return f"diff --git a/{relative_path} b/{relative_path}\n" + "\n".join(body) + "\n"
    if (not original_exists) and updated_exists:
        updated_text = updated_path.read_text(encoding="utf-8", errors="replace")
        body = list(
            unified_diff(
                [],
                updated_text.splitlines(),
                fromfile="/dev/null",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        if not body:
            return ""
        return f"diff --git a/{relative_path} b/{relative_path}\nnew file mode 100644\n" + "\n".join(body) + "\n"
    if original_exists and (not updated_exists):
        original_text = original_path.read_text(encoding="utf-8", errors="replace")
        body = list(
            unified_diff(
                original_text.splitlines(),
                [],
                fromfile=f"a/{relative_path}",
                tofile="/dev/null",
                lineterm="",
            )
        )
        if not body:
            return ""
        return f"diff --git a/{relative_path} b/{relative_path}\n" + "\n".join(body) + "\n"
    return ""


def _build_combined_diff(*, original_root: Path, updated_root: Path, touched_paths: set[str]) -> str:
    chunks: list[str] = []
    for relative_path in sorted(path for path in touched_paths if path.strip()):
        diff_chunk = _build_file_diff(
            relative_path=relative_path,
            original_root=original_root,
            updated_root=updated_root,
        )
        if diff_chunk:
            chunks.append(diff_chunk)
    return "".join(chunks)


def _copy_workspace(source_root: Path, destination_root: Path) -> None:
    ignore = shutil.ignore_patterns(
        ".git",
        ".venv",
        "venv",
        ".venv-smoke",
        ".pytest_cache",
        "__pycache__",
        "dist",
        "*.pyc",
    )
    shutil.copytree(source_root, destination_root, dirs_exist_ok=True, ignore=ignore)


def _run_with_provider_heartbeat(_task_options: Any, _label: str, fn: Any, timeout_seconds: int) -> tuple[Any, bool]:
    _ = timeout_seconds
    return fn(), False


def execute_batch(
    batch: BatchDefinition,
    cwd: Path,
    runtime_context: dict[str, Any],
) -> BatchExecutionResult:
    root = cwd.resolve()
    context = runtime_context if isinstance(runtime_context, dict) else {}
    provider = str(context.get("provider", "openai") or "openai")
    model = str(context.get("model", "openai:gpt-4.1-mini") or "openai:gpt-4.1-mini")
    api_key_env = str(context.get("api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY")
    base_url = str(context.get("base_url", "") or "")
    max_context_chars = int(context.get("max_context_chars", 12000) or 12000)
    provider_timeout = int(context.get("provider_timeout", 60) or 60)

    total_steps = len(batch.operations)
    completed_steps = 0
    touched_paths: set[str] = set()
    step_results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="aegis_batch_") as temp_dir:
        temp_root = Path(temp_dir) / "workspace"
        _copy_workspace(root, temp_root)
        for index, step in enumerate(batch.operations, start=1):
            step_result: dict[str, Any] = {
                "index": index,
                "operation": step.operation,
                "target_file": step.target_file,
                "status": "pending",
                "error": None,
                "patch_generated": False,
            }
            if step.symbol:
                step_result["symbol"] = step.symbol
            if step.anchor:
                step_result["anchor"] = step.anchor
            if step.destination_path:
                step_result["destination_path"] = step.destination_path
            operation_definition = get_operation(step.operation)
            if operation_definition is None or step.operation == "batch":
                step_result["status"] = "blocked"
                step_result["error"] = "operation_contract_invalid"
                step_results.append(step_result)
                return BatchExecutionResult(
                    success=False,
                    diff_text="",
                    total_steps=total_steps,
                    completed_steps=completed_steps,
                    step_results=step_results,
                    failed_step_index=index,
                    error="operation_contract_invalid",
                )
            contract = normalize_operation_contract(
                operation=step.operation,
                target_file=step.target_file,
                destination_path=step.destination_path,
                anchor=step.anchor,
                symbol=step.symbol,
                allow_deletions=bool(operation_definition.allows_deletions),
                allow_new_file=bool(operation_definition.allows_new_files),
                source="cli",
            )
            operation_result = run_operation_stage(
                contract=contract,
                task=step.task,
                cwd=temp_root,
                context={
                    "provider": provider,
                    "model": model,
                    "api_key_env": api_key_env,
                    "base_url": base_url,
                    "max_context_chars": max_context_chars,
                    "task_options": context.get("task_options"),
                    "run_with_provider_heartbeat": _run_with_provider_heartbeat,
                    "generate_structured_edits": generate_structured_edits,
                    "generate_text": generate_text,
                    "build_create_file_prompt": build_create_file_prompt,
                    "build_insert_after_prompt": build_insert_after_prompt,
                    "build_insert_before_prompt": build_insert_before_prompt,
                    "build_replace_block_prompt": build_replace_block_prompt,
                    "build_replace_file_prompt": build_replace_file_prompt,
                    "build_replace_symbol_prompt": build_replace_symbol_prompt,
                    "failure_context": context.get("failure_context", {"files": []}),
                },
                failures={},
                patch_plan={
                    "allowed_targets": [step.target_file],
                    "max_files": 1,
                    "allow_new_files": bool(operation_definition.allows_new_files),
                    "allowed_operations": [step.operation],
                },
                aegis_execution=context.get("aegis_execution", {}),
                model=model,
                provider_timeout=provider_timeout,
            )
            operation_status = str(operation_result.status or "blocked")
            operation_error = str(operation_result.error or "operation_validation_failed")
            has_diff = bool(str(operation_result.diff_text or "").strip())
            if operation_status != "generated" or not has_diff:
                step_result["status"] = operation_status
                step_result["error"] = operation_error
                step_result["patch_generated"] = has_diff
                step_results.append(step_result)
                return BatchExecutionResult(
                    success=False,
                    diff_text="",
                    total_steps=total_steps,
                    completed_steps=completed_steps,
                    step_results=step_results,
                    failed_step_index=index,
                    error=operation_error,
                )
            applied_ok, apply_error, step_touched = _apply_step_diff(
                diff_text=str(operation_result.diff_text or ""),
                workspace_root=temp_root,
            )
            if not applied_ok:
                step_result["status"] = "apply_failed"
                step_result["error"] = str(apply_error or "operation_validation_failed")
                step_result["patch_generated"] = True
                step_results.append(step_result)
                return BatchExecutionResult(
                    success=False,
                    diff_text="",
                    total_steps=total_steps,
                    completed_steps=completed_steps,
                    step_results=step_results,
                    failed_step_index=index,
                    error=str(apply_error or "operation_validation_failed"),
                )
            touched_paths.update(step_touched)
            completed_steps += 1
            step_result["status"] = "generated"
            step_result["error"] = None
            step_result["patch_generated"] = True
            step_results.append(step_result)
        combined_diff = _build_combined_diff(
            original_root=root,
            updated_root=temp_root,
            touched_paths=touched_paths,
        )
    if not str(combined_diff or "").strip():
        return BatchExecutionResult(
            success=False,
            diff_text="",
            total_steps=total_steps,
            completed_steps=completed_steps,
            step_results=step_results,
            failed_step_index=None,
            error="operation_validation_failed",
        )
    return BatchExecutionResult(
        success=True,
        diff_text=combined_diff,
        total_steps=total_steps,
        completed_steps=completed_steps,
        step_results=step_results,
        failed_step_index=None,
        error=None,
    )
