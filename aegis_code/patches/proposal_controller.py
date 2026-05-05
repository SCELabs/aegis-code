from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aegis_code.patches.structured_edits import parse_structured_edit_response, structured_edits_to_diff


@dataclass(slots=True)
class ProposalContract:
    allowed_targets: list[str] = field(default_factory=list)
    allowed_operations: list[str] = field(default_factory=lambda: ["replace", "create"])
    forbidden_operations: list[str] = field(default_factory=lambda: ["delete", "rename"])
    max_files: int | None = None
    allow_new_files: bool = False
    require_tests: bool = False
    task_type: str = "general"
    verification_command: str | None = None
    stack_hints: dict[str, Any] | list[Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProposalAttemptResult:
    ok: bool
    diff: str
    errors: list[str]
    warnings: list[str]
    files: list[str]
    status: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)
    retry_count: int = 0
    attempt_number: int = 1


_CORRECTABLE = {
    "invalid_json",
    "invalid_schema",
    "invalid_path",
    "outside_allowed_targets",
    "create_target_exists",
    "replace_target_missing",
    "unsupported_mode",
    "empty_diff",
    "too_many_files",
}


def classify_structured_failure(errors: list[str]) -> str:
    values = [str(item) for item in (errors or [])]
    if not values:
        return "unknown"
    first = values[0]
    if first.startswith("invalid_path:outside_allowed_targets"):
        return "outside_allowed_targets"
    if first.startswith("invalid_path:"):
        return "invalid_path"
    mapping = {
        "create_target_exists": "create_target_exists",
        "replace_target_missing": "replace_target_missing",
        "binary_content": "unsafe_content",
        "unsupported_mode": "unsupported_mode",
        "empty_diff": "empty_diff",
        "invalid_diff": "invalid_diff",
        "invalid_json": "invalid_json",
        "invalid_json_root": "invalid_schema",
        "invalid_changes": "invalid_schema",
        "too_many_files": "too_many_files",
    }
    return mapping.get(first, "unknown")


def _build_retry_task(task: str, reason: str, errors: list[str], contract: ProposalContract) -> str:
    allowed_targets = ", ".join(contract.allowed_targets) if contract.allowed_targets else "(none specified)"
    allowed_ops = ", ".join(contract.allowed_operations) if contract.allowed_operations else "(none)"
    err_text = ", ".join(str(item) for item in errors) if errors else "none"
    return (
        f"{task}\n\n"
        "Structured proposal correction required.\n"
        f"Previous failure reason: {reason}\n"
        f"Previous errors: {err_text}\n"
        f"Allowed targets: {allowed_targets}\n"
        f"Allowed operations: {allowed_ops}\n"
        f"Allow new files: {contract.allow_new_files}\n"
        "Return JSON only.\n"
        "Do not use unified diff.\n"
        "Do not create files unless allowed.\n"
        "Do not touch files outside allowed targets.\n"
    )


def _validate_contract(parsed_edits: dict[str, Any], converted: dict[str, Any], contract: ProposalContract) -> list[str]:
    errors: list[str] = []
    changes = parsed_edits.get("changes", []) if isinstance(parsed_edits, dict) else []
    if not isinstance(changes, list):
        changes = []
    for item in changes:
        if not isinstance(item, dict):
            continue
        mode = str(item.get("mode", "") or "").strip().lower()
        if mode and contract.allowed_operations and mode not in set(contract.allowed_operations):
            errors.append("unsupported_mode")
            break
        if mode == "create" and not contract.allow_new_files:
            errors.append("unsupported_mode")
            break
    files = converted.get("files", [])
    if not isinstance(files, list):
        files = []
    if contract.max_files is not None and len(files) > int(contract.max_files):
        errors.append("too_many_files")
    return errors


def build_proposal_contract(
    *,
    task: str,
    patch_plan: dict[str, Any],
    verification_command: str | None,
    stack_hints: dict[str, Any] | list[Any],
) -> ProposalContract:
    task_type = str(patch_plan.get("task_type", "") or "general")
    allowed_targets = [str(item) for item in patch_plan.get("allowed_targets", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_targets", []), list) else []
    if task_type == "test_generation":
        allowed_targets = [path for path in allowed_targets if path.startswith("tests/")]
    if task_type == "docs_task":
        allowed_targets = [path for path in allowed_targets if path == "README.md" or path.startswith("docs/")]
    if task_type == "general" and not allowed_targets:
        proposed = patch_plan.get("proposed_changes", [])
        if isinstance(proposed, list):
            for item in proposed:
                if isinstance(item, dict):
                    path = str(item.get("file", "")).strip()
                    if path:
                        allowed_targets.append(path)
    allow_new_files = bool(patch_plan.get("allow_new_files", False)) or any(str(item.get("change_type", "")).strip().lower() == "create" for item in patch_plan.get("proposed_changes", []) if isinstance(item, dict))
    lowered_task = str(task or "").lower()
    if any(token in lowered_task for token in ("create ", "add file", "new module", "scaffold")):
        allow_new_files = True
    if task_type == "docs_task":
        allow_new_files = False
    if task_type == "test_generation":
        allow_new_files = all(str(path).startswith("tests/") for path in allowed_targets) if allowed_targets else True
    max_files = int(patch_plan.get("max_files", 0) or 0) if isinstance(patch_plan.get("max_files"), int) else (len(allowed_targets) if allowed_targets else None)
    if isinstance(max_files, int) and max_files <= 0:
        max_files = None
    configured_ops = [str(item).strip().lower() for item in patch_plan.get("allowed_operations", []) if str(item).strip()] if isinstance(patch_plan.get("allowed_operations", []), list) else []
    allowed_operations = configured_ops or (["create", "replace"] if allow_new_files else ["replace"])
    return ProposalContract(
        allowed_targets=allowed_targets,
        allowed_operations=allowed_operations,
        forbidden_operations=["delete", "rename"],
        max_files=max_files,
        allow_new_files=allow_new_files,
        require_tests=task_type in {"test_generation", "implementation_with_tests"},
        task_type=task_type,
        verification_command=verification_command,
        stack_hints=stack_hints,
    )


def run_structured_proposal_controller(
    *,
    task: str,
    cwd: Path,
    contract: ProposalContract,
    attempt_fn: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    retry_count = 0
    retry_attempted = False
    current_task = task
    last_result: ProposalAttemptResult | None = None
    for attempt_number in (1, 2):
        provider_result = attempt_fn(current_task)
        if not bool(provider_result.get("available", False)):
            return {
                "attempted": False,
                "available": False,
                "status": "skipped",
                "failure_reason": "provider_unavailable",
                "errors": [str(provider_result.get("error", "provider_unavailable"))],
                "retry_attempted": retry_attempted,
                "retry_count": retry_count,
                "result": None,
                "provider_result": provider_result,
            }
        parsed = parse_structured_edit_response(str(provider_result.get("text", "") or ""))
        if not bool(parsed.get("ok", False)):
            errors = [str(item) for item in parsed.get("errors", [])]
            reason = classify_structured_failure(errors)
            last_result = ProposalAttemptResult(
                ok=False,
                diff="",
                errors=errors,
                warnings=[],
                files=[],
                status=reason,
                provider_metadata={"provider_result": provider_result},
                retry_count=retry_count,
                attempt_number=attempt_number,
            )
        else:
            converted = structured_edits_to_diff(
                parsed.get("edits", {}),
                cwd=cwd,
                allowed_targets=contract.allowed_targets or None,
            )
            errors = [str(item) for item in converted.get("errors", [])]
            errors.extend(_validate_contract(parsed.get("edits", {}), converted, contract))
            reason = classify_structured_failure(errors)
            last_result = ProposalAttemptResult(
                ok=not errors and bool(converted.get("ok", False)),
                diff=str(converted.get("diff", "") or ""),
                errors=errors,
                warnings=[str(item) for item in converted.get("warnings", [])],
                files=[str(item) for item in converted.get("files", [])],
                status="accepted" if not errors and bool(converted.get("ok", False)) else reason,
                provider_metadata={"provider_result": provider_result},
                retry_count=retry_count,
                attempt_number=attempt_number,
            )
        if last_result.ok:
            return {
                "attempted": True,
                "available": True,
                "status": "accepted",
                "failure_reason": None,
                "errors": [],
                "retry_attempted": retry_attempted,
                "retry_count": retry_count,
                "result": last_result,
                "provider_result": provider_result,
            }
        if attempt_number == 1 and last_result.status in _CORRECTABLE:
            retry_attempted = True
            retry_count = 1
            current_task = _build_retry_task(task, last_result.status, last_result.errors, contract)
            continue
        break
    return {
        "attempted": True,
        "available": False,
        "status": "failed",
        "failure_reason": last_result.status if last_result else "unknown",
        "errors": list(last_result.errors) if last_result else ["unknown"],
        "retry_attempted": retry_attempted,
        "retry_count": retry_count,
        "result": last_result,
        "provider_result": (last_result.provider_metadata.get("provider_result", {}) if last_result else {}),
    }
