from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from aegis_code.config import project_paths
from aegis_code.next_actions import build_next_actions
from aegis_code.patches.diff_inspector import inspect_diff
from aegis_code.patches.apply_check import check_patch_file
from aegis_code.patches.patch_applier import apply_patch_file
from aegis_code.report import read_latest_markdown

from aegis_code.api.errors import AegisApplyError, AegisPatchError, AegisReportError


@dataclass(frozen=True, slots=True)
class SetupStatus:
    initialized: bool
    aegis_key: bool
    provider_key: bool
    provider_preset: bool
    context_available: bool
    latest_run: bool
    verification_available: bool
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SetupStatus":
        return cls(
            initialized=bool(data.get("initialized", False)),
            aegis_key=bool(data.get("aegis_key", False)),
            provider_key=bool(data.get("provider_key", False)),
            provider_preset=bool(data.get("provider_preset", False)),
            context_available=bool(data.get("context_available", False)),
            latest_run=bool(data.get("latest_run", False)),
            verification_available=bool(data.get("verification_available", False)),
            raw=dict(data),
        )


@dataclass(frozen=True, slots=True)
class ApplyResult:
    applied: bool
    valid: bool | None
    apply_blocked: bool | None
    path: str | None
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    files_changed: tuple[str, ...]
    raw: dict[str, Any]

    @classmethod
    def from_check_result(cls, data: dict[str, Any]) -> "ApplyResult":
        return cls(
            applied=False,
            valid=bool(data.get("valid", False)),
            apply_blocked=bool(data.get("apply_blocked", False)),
            path=str(data.get("path")) if data.get("path") is not None else None,
            warnings=tuple(str(item) for item in data.get("warnings", []) if item is not None),
            errors=tuple(str(item) for item in data.get("errors", []) if item is not None),
            files_changed=tuple(),
            raw=dict(data),
        )

    @classmethod
    def from_apply_result(cls, data: dict[str, Any]) -> "ApplyResult":
        changed: list[str] = []
        for item in data.get("files_changed", []):
            if isinstance(item, dict) and item.get("path") is not None:
                changed.append(str(item.get("path")))
        return cls(
            applied=bool(data.get("applied", False)),
            valid=None,
            apply_blocked=None,
            path=str(data.get("path")) if data.get("path") is not None else None,
            warnings=tuple(str(item) for item in data.get("warnings", []) if item is not None),
            errors=tuple(str(item) for item in data.get("errors", []) if item is not None),
            files_changed=tuple(changed),
            raw=dict(data),
        )


@dataclass(frozen=True, slots=True)
class PatchProposal:
    status: str
    diff_path: Path | None
    error: str | None
    operation: str | None
    payload: dict[str, Any]
    project_path: Path

    def diff_text(self, *, path: str | Path | None = None) -> str:
        if path is None:
            target = self.diff_path
        else:
            raw = Path(path)
            target = raw if raw.is_absolute() else (self.project_path / raw)
        if target is None:
            raise AegisPatchError("No diff path is available for this proposal.")
        try:
            return target.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise AegisPatchError(f"Diff file not found: {target}") from exc
        except Exception as exc:
            raise AegisPatchError(f"Failed to read diff file: {target}") from exc

    def inspect_diff(self, *, path: str | Path | None = None) -> dict[str, Any]:
        diff = self.diff_text(path=path)
        try:
            return inspect_diff(diff, cwd=self.project_path)
        except Exception as exc:
            raise AegisPatchError("Failed to inspect diff contents.") from exc

    def apply(self, *, check: bool = True, path: str | Path | None = None) -> ApplyResult:
        if path is None:
            target = self.diff_path
        else:
            raw = Path(path)
            target = raw if raw.is_absolute() else (self.project_path / raw)
        if target is None:
            raise AegisApplyError("No diff path is available for apply/check.")
        if check:
            try:
                checked = check_patch_file(target, cwd=self.project_path)
            except Exception as exc:
                raise AegisApplyError(f"Patch check failed for {target}") from exc
            return ApplyResult.from_check_result(checked)
        try:
            applied = apply_patch_file(target, cwd=self.project_path)
        except Exception as exc:
            raise AegisApplyError(f"Patch apply failed for {target}") from exc
        return ApplyResult.from_apply_result(applied)


@dataclass(frozen=True, slots=True)
class RunStatus:
    available: bool
    task: str | None
    run_status: str | None
    failure_count: int
    payload: dict[str, Any] | None

    @property
    def raw(self) -> dict[str, Any] | None:
        return self.payload


@dataclass(frozen=True, slots=True)
class ReportSummary:
    task: str | None
    status: str | None
    mode: str | None
    dry_run: bool
    failure_count: int
    apply_safety: str | None


@dataclass(frozen=True, slots=True)
class PatchSummary:
    status: str
    operation: str | None
    diff_path: Path | None
    available: bool
    attempted: bool
    safety: str | None
    error: str | None
    files_touched: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    available: bool
    detected_stack: str | None
    test_command: str | None
    confidence: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class ModelSelectionSummary:
    provider: str | None
    model: str | None
    tier: str | None
    mode: str | None
    reason: str | None
    provider_timeout_seconds: int | None


@dataclass(frozen=True, slots=True)
class RuntimeControlSummary:
    mode: str | None
    reason: str | None
    budget_available: bool
    budget_remaining: float | None
    context_available: bool


@dataclass(frozen=True, slots=True)
class NextAction:
    index: int
    description: str
    rule: str | None


@dataclass(frozen=True, slots=True)
class RunReport:
    available: bool
    markdown_path: Path | None
    markdown: str | None
    json_path: Path | None
    payload: dict[str, Any] | None
    project_path: Path | None = None

    @classmethod
    def load(cls, project_path: Path) -> "RunReport":
        try:
            latest_markdown = read_latest_markdown(project_path)
        except Exception as exc:
            raise AegisReportError("Failed to read latest markdown report.") from exc
        markdown_path: Path | None = None
        markdown: str | None = None
        if latest_markdown is not None:
            markdown_path, markdown = latest_markdown
        json_path = project_paths(project_path)["latest_json"]
        payload: dict[str, Any] | None = None
        if json_path.exists():
            try:
                loaded = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except json.JSONDecodeError as exc:
                raise AegisReportError(f"Latest report JSON is invalid: {json_path}") from exc
            except Exception as exc:
                raise AegisReportError(f"Failed to load latest report JSON: {json_path}") from exc
        return cls(
            available=bool(markdown_path is not None or payload is not None),
            markdown_path=markdown_path,
            markdown=markdown,
            json_path=json_path if json_path.exists() else None,
            payload=payload,
            project_path=project_path,
        )

    @property
    def raw(self) -> dict[str, Any] | None:
        return self.payload

    def _payload(self) -> dict[str, Any]:
        return dict(self.payload) if isinstance(self.payload, dict) else {}

    @property
    def summary(self) -> ReportSummary:
        payload = self._payload()
        failures = payload.get("final_failures", {}) if isinstance(payload.get("final_failures"), dict) else {}
        if not failures:
            failures = payload.get("failures", {}) if isinstance(payload.get("failures"), dict) else {}
        return ReportSummary(
            task=str(payload.get("task")) if payload.get("task") is not None else None,
            status=str(payload.get("status")) if payload.get("status") is not None else None,
            mode=str(payload.get("mode")) if payload.get("mode") is not None else None,
            dry_run=bool(payload.get("dry_run", False)),
            failure_count=int(failures.get("failure_count", 0) or 0),
            apply_safety=str(payload.get("apply_safety")) if payload.get("apply_safety") is not None else None,
        )

    @property
    def patch(self) -> PatchSummary:
        payload = self._payload()
        patch_diff = payload.get("patch_diff", {}) if isinstance(payload.get("patch_diff"), dict) else {}
        patch_operation = payload.get("patch_operation", {}) if isinstance(payload.get("patch_operation"), dict) else {}
        patch_quality = payload.get("patch_quality", {}) if isinstance(payload.get("patch_quality"), dict) else {}
        patch_safety = payload.get("patch_safety", {}) if isinstance(payload.get("patch_safety"), dict) else {}
        diff_path: Path | None = None
        diff_path_value = patch_diff.get("path")
        if isinstance(diff_path_value, str) and diff_path_value.strip():
            candidate = Path(diff_path_value)
            if candidate.is_absolute():
                diff_path = candidate
            elif self.project_path is not None:
                diff_path = self.project_path / candidate
            else:
                diff_path = candidate
        safety = payload.get("apply_safety")
        if safety is None:
            safety = patch_diff.get("apply_safety")
        if safety is None:
            safety = patch_quality.get("apply_safety")
        if safety is None:
            safety = patch_safety.get("highest_severity")
        touched = patch_diff.get("touched_files", []) if isinstance(patch_diff.get("touched_files"), list) else []
        files_touched = tuple(str(item) for item in touched if item is not None)
        return PatchSummary(
            status=str(patch_diff.get("status", "skipped") or "skipped"),
            operation=str(patch_operation.get("operation")) if patch_operation.get("operation") is not None else None,
            diff_path=diff_path,
            available=bool(patch_diff.get("available", False)),
            attempted=bool(patch_diff.get("attempted", False)),
            safety=str(safety) if safety is not None else None,
            error=str(patch_diff.get("error")) if patch_diff.get("error") is not None else None,
            files_touched=files_touched,
        )

    @property
    def verification(self) -> VerificationSummary:
        payload = self._payload()
        verification = payload.get("verification", {}) if isinstance(payload.get("verification"), dict) else {}
        return VerificationSummary(
            available=bool(verification.get("available", False)),
            detected_stack=str(verification.get("detected_stack")) if verification.get("detected_stack") is not None else None,
            test_command=str(verification.get("test_command")) if verification.get("test_command") is not None else None,
            confidence=str(verification.get("confidence")) if verification.get("confidence") is not None else None,
            reason=str(verification.get("reason")) if verification.get("reason") is not None else None,
        )

    @property
    def model_selection(self) -> ModelSelectionSummary:
        payload = self._payload()
        selection = payload.get("model_selection", {}) if isinstance(payload.get("model_selection"), dict) else {}
        provider_timeout_seconds = selection.get("provider_timeout_seconds")
        timeout_int: int | None = None
        if provider_timeout_seconds is not None:
            try:
                timeout_int = int(provider_timeout_seconds)
            except Exception:
                timeout_int = None
        mode_value = selection.get("mode")
        if mode_value is None:
            mode_value = payload.get("mode")
        reason_value = selection.get("reason")
        if reason_value is None:
            runtime_policy = payload.get("runtime_policy", {}) if isinstance(payload.get("runtime_policy"), dict) else {}
            reason_value = runtime_policy.get("reason")
        return ModelSelectionSummary(
            provider=str(selection.get("provider")) if selection.get("provider") is not None else None,
            model=str(selection.get("model")) if selection.get("model") is not None else None,
            tier=str(selection.get("tier")) if selection.get("tier") is not None else None,
            mode=str(mode_value) if mode_value is not None else None,
            reason=str(reason_value) if reason_value is not None else None,
            provider_timeout_seconds=timeout_int,
        )

    @property
    def runtime_control(self) -> RuntimeControlSummary:
        payload = self._payload()
        runtime_policy = payload.get("runtime_policy", {}) if isinstance(payload.get("runtime_policy"), dict) else {}
        budget_state = payload.get("budget_state", {}) if isinstance(payload.get("budget_state"), dict) else {}
        project_context = payload.get("project_context", {}) if isinstance(payload.get("project_context"), dict) else {}
        remaining = budget_state.get("remaining_estimate")
        remaining_float: float | None = None
        if remaining is not None:
            try:
                remaining_float = float(remaining)
            except Exception:
                remaining_float = None
        return RuntimeControlSummary(
            mode=str(runtime_policy.get("selected_mode")) if runtime_policy.get("selected_mode") is not None else None,
            reason=str(runtime_policy.get("reason")) if runtime_policy.get("reason") is not None else None,
            budget_available=bool(budget_state.get("available", False)),
            budget_remaining=remaining_float,
            context_available=bool(project_context.get("available", False)),
        )

    @property
    def next_actions(self) -> tuple[NextAction, ...]:
        payload = self._payload()
        if not payload:
            return tuple()
        data = build_next_actions(payload, cwd=self.project_path)
        actions = data.get("actions", []) if isinstance(data.get("actions"), list) else []
        rule = str(data.get("rule")) if data.get("rule") is not None else None
        normalized: list[NextAction] = []
        for idx, item in enumerate(actions, start=1):
            normalized.append(NextAction(index=idx, description=str(item), rule=rule))
        return tuple(normalized)
