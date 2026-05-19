from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aegis_code.api.errors import (
    AegisApiError,
    AegisApplyError,
    AegisPatchError,
    AegisReportError,
    AegisSetupError,
)
from aegis_code.api.types import ApplyResult, PatchProposal, RunReport, RunStatus, SetupStatus

API_VERSION = "1"


def _timestamp_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def _meta(*, workspace: str | Path | None = None, api_version: str = API_VERSION, timestamp: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "api_version": str(api_version),
        "timestamp": str(timestamp or _timestamp_utc()),
    }
    if workspace is not None:
        meta["workspace"] = str(workspace)
    return meta


@dataclass(frozen=True, slots=True)
class SetupCheckRequest:
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {"project_path": self.workspace}


@dataclass(frozen=True, slots=True)
class PatchRequest:
    task: str
    files: tuple[str, ...]
    operation: str | None = None
    anchor: str | None = None
    symbol: str | None = None
    allow_create: bool = False
    max_files: int | None = None
    dry_run: bool = False
    mode: str | None = None
    target: str | None = None
    budget: float | None = None
    analyze_failures: bool = True
    session: str | None = None
    no_report: bool = False
    provider_timeout_seconds: int | None = None
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "files": [str(item) for item in self.files],
            "operation": self.operation,
            "anchor": self.anchor,
            "symbol": self.symbol,
            "allow_create": bool(self.allow_create),
            "max_files": self.max_files,
            "dry_run": bool(self.dry_run),
            "mode": self.mode,
            "target": self.target,
            "budget": self.budget,
            "analyze_failures": bool(self.analyze_failures),
            "session": self.session,
            "no_report": bool(self.no_report),
            "provider_timeout_seconds": self.provider_timeout_seconds,
            "project_path": self.workspace,
        }


@dataclass(frozen=True, slots=True)
class ApplyCheckRequest:
    diff_path: str | None = None
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {"path": self.diff_path, "check": True, "project_path": self.workspace}


@dataclass(frozen=True, slots=True)
class ApplyConfirmRequest:
    diff_path: str | None = None
    run_tests: bool = False
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {"path": self.diff_path, "check": False, "project_path": self.workspace}


@dataclass(frozen=True, slots=True)
class StatusRequest:
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {"project_path": self.workspace}


@dataclass(frozen=True, slots=True)
class ReportRequest:
    workspace: str = "."

    def to_api_kwargs(self) -> dict[str, Any]:
        return {"project_path": self.workspace}


def setup_status_to_dict(value: SetupStatus) -> dict[str, Any]:
    return _json_safe(
        {
            "initialized": bool(value.initialized),
            "aegis_key": bool(value.aegis_key),
            "provider_key": bool(value.provider_key),
            "provider_preset": bool(value.provider_preset),
            "context_available": bool(value.context_available),
            "latest_run": bool(value.latest_run),
            "verification_available": bool(value.verification_available),
            "raw": dict(value.raw),
        }
    )


def patch_proposal_to_dict(value: PatchProposal) -> dict[str, Any]:
    return _json_safe(
        {
            "status": str(value.status),
            "diff_path": str(value.diff_path) if value.diff_path is not None else None,
            "error": value.error,
            "operation": value.operation,
            "payload": dict(value.payload),
            "raw": dict(value.payload),
        }
    )


def apply_result_to_dict(value: ApplyResult) -> dict[str, Any]:
    return _json_safe(
        {
            "applied": bool(value.applied),
            "valid": value.valid,
            "apply_blocked": value.apply_blocked,
            "path": value.path,
            "warnings": list(value.warnings),
            "errors": list(value.errors),
            "files_changed": list(value.files_changed),
            "raw": dict(value.raw),
        }
    )


def run_status_to_dict(value: RunStatus) -> dict[str, Any]:
    payload = dict(value.payload) if isinstance(value.payload, dict) else None
    return _json_safe(
        {
            "available": bool(value.available),
            "task": value.task,
            "run_status": value.run_status,
            "failure_count": int(value.failure_count),
            "payload": payload,
            "raw": payload,
        }
    )


def run_report_to_dict(value: RunReport) -> dict[str, Any]:
    payload = dict(value.payload) if isinstance(value.payload, dict) else None
    return _json_safe(
        {
            "available": bool(value.available),
            "markdown_path": str(value.markdown_path) if value.markdown_path is not None else None,
            "markdown": value.markdown,
            "json_path": str(value.json_path) if value.json_path is not None else None,
            "payload": payload,
            "raw": payload,
            "summary": asdict(value.summary),
            "patch": asdict(value.patch),
            "verification": asdict(value.verification),
            "model_selection": asdict(value.model_selection),
            "runtime_control": asdict(value.runtime_control),
            "next_actions": [asdict(item) for item in value.next_actions],
        }
    )


@dataclass(frozen=True, slots=True)
class SetupCheckResponse:
    setup: dict[str, Any]

    @classmethod
    def from_status(cls, value: SetupStatus) -> "SetupCheckResponse":
        return cls(setup=setup_status_to_dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"setup": self.setup}


@dataclass(frozen=True, slots=True)
class PatchResponse:
    patch: dict[str, Any]

    @classmethod
    def from_proposal(cls, value: PatchProposal) -> "PatchResponse":
        return cls(patch=patch_proposal_to_dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"patch": self.patch}


@dataclass(frozen=True, slots=True)
class ApplyResponse:
    apply: dict[str, Any]

    @classmethod
    def from_result(cls, value: ApplyResult) -> "ApplyResponse":
        return cls(apply=apply_result_to_dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"apply": self.apply}


@dataclass(frozen=True, slots=True)
class StatusResponse:
    status: dict[str, Any]

    @classmethod
    def from_status(cls, value: RunStatus) -> "StatusResponse":
        return cls(status=run_status_to_dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status}


@dataclass(frozen=True, slots=True)
class ReportResponse:
    report: dict[str, Any]

    @classmethod
    def from_report(cls, value: RunReport) -> "ReportResponse":
        return cls(report=run_report_to_dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {"report": self.report}


def serialize_data(value: Any) -> dict[str, Any]:
    if isinstance(value, SetupStatus):
        return setup_status_to_dict(value)
    if isinstance(value, PatchProposal):
        return patch_proposal_to_dict(value)
    if isinstance(value, ApplyResult):
        return apply_result_to_dict(value)
    if isinstance(value, RunStatus):
        return run_status_to_dict(value)
    if isinstance(value, RunReport):
        return run_report_to_dict(value)
    if isinstance(value, SetupCheckResponse):
        return value.to_dict()
    if isinstance(value, PatchResponse):
        return value.to_dict()
    if isinstance(value, ApplyResponse):
        return value.to_dict()
    if isinstance(value, StatusResponse):
        return value.to_dict()
    if isinstance(value, ReportResponse):
        return value.to_dict()
    if isinstance(value, dict):
        return _json_safe(dict(value))
    raise TypeError(f"Unsupported response data type: {type(value).__name__}")


def to_response(
    value: Any,
    *,
    workspace: str | Path | None = None,
    api_version: str = API_VERSION,
    timestamp: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "data": serialize_data(value),
        "error": None,
        "meta": _meta(workspace=workspace, api_version=api_version, timestamp=timestamp),
    }


def _error_defaults(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, AegisSetupError):
        return {"code": "SETUP_ERROR", "category": "setup"}
    if isinstance(exc, AegisPatchError):
        return {"code": "PATCH_ERROR", "category": "patch"}
    if isinstance(exc, AegisApplyError):
        return {"code": "APPLY_ERROR", "category": "apply"}
    if isinstance(exc, AegisReportError):
        return {"code": "REPORT_ERROR", "category": "report"}
    if isinstance(exc, AegisApiError):
        return {"code": "AEGIS_API_ERROR", "category": "api"}
    return {"code": "INTERNAL_ERROR", "category": "internal"}


def to_error(
    exc: Exception,
    *,
    workspace: str | Path | None = None,
    api_version: str = API_VERSION,
    timestamp: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged_details = _error_defaults(exc)
    if details:
        merged_details.update(_json_safe(details))
    return {
        "ok": False,
        "data": None,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc) if str(exc) else exc.__class__.__name__,
            "details": merged_details,
        },
        "meta": _meta(workspace=workspace, api_version=api_version, timestamp=timestamp),
    }

