from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import aegis_code.api as api
import aegis_code.server.contracts as contracts
import aegis_code.server.guards as guards


def _workspace_from_mapping(payload: Mapping[str, Any], *, default_workspace: str = ".") -> str:
    return guards.normalize_workspace(str(payload.get("workspace", default_workspace)))


def _coerce_setup_request(request: contracts.SetupCheckRequest | Mapping[str, Any] | None) -> contracts.SetupCheckRequest:
    if isinstance(request, contracts.SetupCheckRequest):
        return request
    if request is None:
        return contracts.SetupCheckRequest()
    payload = guards.require_mapping(request, label="setup_check request")
    guards.validate_request_size(payload)
    return contracts.SetupCheckRequest(workspace=_workspace_from_mapping(payload))


def _coerce_status_request(request: contracts.StatusRequest | Mapping[str, Any] | None) -> contracts.StatusRequest:
    if isinstance(request, contracts.StatusRequest):
        return request
    if request is None:
        return contracts.StatusRequest()
    payload = guards.require_mapping(request, label="status request")
    guards.validate_request_size(payload)
    return contracts.StatusRequest(workspace=_workspace_from_mapping(payload))


def _coerce_report_request(request: contracts.ReportRequest | Mapping[str, Any] | None) -> contracts.ReportRequest:
    if isinstance(request, contracts.ReportRequest):
        return request
    if request is None:
        return contracts.ReportRequest()
    payload = guards.require_mapping(request, label="report request")
    guards.validate_request_size(payload)
    return contracts.ReportRequest(workspace=_workspace_from_mapping(payload))


def _coerce_patch_request(request: contracts.PatchRequest | Mapping[str, Any]) -> contracts.PatchRequest:
    if isinstance(request, contracts.PatchRequest):
        guards.validate_patch_inputs(task=request.task, files=request.files, anchor=request.anchor, symbol=request.symbol)
        return request
    payload = guards.require_mapping(request, label="patch request")
    guards.validate_request_size(payload)
    files_value = payload.get("files", ())
    if isinstance(files_value, (list, tuple)):
        files = tuple(str(item) for item in files_value)
    else:
        files = tuple()
    dto = contracts.PatchRequest(
        task=str(payload.get("task", "")),
        files=files,
        operation=str(payload.get("operation")) if payload.get("operation") is not None else None,
        anchor=str(payload.get("anchor")) if payload.get("anchor") is not None else None,
        symbol=str(payload.get("symbol")) if payload.get("symbol") is not None else None,
        allow_create=bool(payload.get("allow_create", False)),
        max_files=int(payload["max_files"]) if payload.get("max_files") is not None else None,
        dry_run=bool(payload.get("dry_run", False)),
        mode=str(payload.get("mode")) if payload.get("mode") is not None else None,
        target=str(payload.get("target")) if payload.get("target") is not None else None,
        budget=float(payload["budget"]) if payload.get("budget") is not None else None,
        analyze_failures=bool(payload.get("analyze_failures", True)),
        session=str(payload.get("session")) if payload.get("session") is not None else None,
        no_report=bool(payload.get("no_report", False)),
        provider_timeout_seconds=(
            int(payload["provider_timeout_seconds"]) if payload.get("provider_timeout_seconds") is not None else None
        ),
        workspace=_workspace_from_mapping(payload),
    )
    guards.validate_patch_inputs(task=dto.task, files=dto.files, anchor=dto.anchor, symbol=dto.symbol)
    return dto


def _coerce_apply_check_request(
    request: contracts.ApplyCheckRequest | Mapping[str, Any] | None,
) -> contracts.ApplyCheckRequest:
    if isinstance(request, contracts.ApplyCheckRequest):
        guards.validate_diff_path(request.diff_path)
        return request
    if request is None:
        dto = contracts.ApplyCheckRequest()
        guards.validate_diff_path(dto.diff_path)
        return dto
    payload = guards.require_mapping(request, label="apply_check request")
    guards.validate_request_size(payload)
    dto = contracts.ApplyCheckRequest(
        diff_path=str(payload.get("diff_path")) if payload.get("diff_path") is not None else None,
        workspace=_workspace_from_mapping(payload),
    )
    guards.validate_diff_path(dto.diff_path)
    return dto


def _coerce_apply_confirm_request(
    request: contracts.ApplyConfirmRequest | Mapping[str, Any] | None,
) -> contracts.ApplyConfirmRequest:
    if isinstance(request, contracts.ApplyConfirmRequest):
        guards.validate_diff_path(request.diff_path)
        return request
    if request is None:
        dto = contracts.ApplyConfirmRequest()
        guards.validate_diff_path(dto.diff_path)
        return dto
    payload = guards.require_mapping(request, label="apply_confirm request")
    guards.validate_request_size(payload)
    dto = contracts.ApplyConfirmRequest(
        diff_path=str(payload.get("diff_path")) if payload.get("diff_path") is not None else None,
        run_tests=bool(payload.get("run_tests", False)),
        workspace=_workspace_from_mapping(payload),
    )
    guards.validate_diff_path(dto.diff_path)
    return dto


def health_handler(*, workspace: str | None = None) -> dict[str, Any]:
    resolved_workspace = guards.normalize_workspace(workspace)
    return contracts.to_response(
        {
            "health": {
                "status": "ok",
                "ready": True,
                "api_version": contracts.API_VERSION,
                "workspace_validated": True,
            }
        },
        workspace=resolved_workspace,
    )


def setup_check_handler(request: contracts.SetupCheckRequest | Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        dto = _coerce_setup_request(request)
        result = api.setup_check(**dto.to_api_kwargs())
        return contracts.to_response(contracts.SetupCheckResponse.from_status(result), workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.SetupCheckRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "setup_check_handler"})


def status_handler(request: contracts.StatusRequest | Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        dto = _coerce_status_request(request)
        result = api.status(**dto.to_api_kwargs())
        return contracts.to_response(contracts.StatusResponse.from_status(result), workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.StatusRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "status_handler"})


def report_handler(request: contracts.ReportRequest | Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        dto = _coerce_report_request(request)
        result = api.report(**dto.to_api_kwargs())
        return contracts.to_response(contracts.ReportResponse.from_report(result), workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.ReportRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "report_handler"})


def latest_diff_handler(
    request: contracts.ReportRequest | Mapping[str, Any] | None = None,
    *,
    include_text: bool = True,
    max_text_bytes: int = guards.MAX_DIFF_TEXT_BYTES,
) -> dict[str, Any]:
    try:
        dto = _coerce_report_request(request)
        client = api.AegisCode(project_path=dto.workspace)
        latest_path = client.latest_diff()
        if latest_path is None:
            data = {"latest_diff": {"available": False, "path": None, "text": None, "truncated": False}}
            return contracts.to_response(data, workspace=dto.workspace)
        text: str | None = None
        truncated = False
        if include_text:
            raw_text = Path(latest_path).read_text(encoding="utf-8")
            encoded = raw_text.encode("utf-8")
            if len(encoded) > max_text_bytes:
                text = encoded[:max_text_bytes].decode("utf-8", errors="ignore")
                truncated = True
            else:
                text = raw_text
        data = {
            "latest_diff": {
                "available": True,
                "path": str(latest_path),
                "text": text,
                "truncated": truncated,
            }
        }
        return contracts.to_response(data, workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.ReportRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "latest_diff_handler"})


def patch_handler(request: contracts.PatchRequest | Mapping[str, Any]) -> dict[str, Any]:
    try:
        dto = _coerce_patch_request(request)
        result = api.patch(**dto.to_api_kwargs())
        return contracts.to_response(contracts.PatchResponse.from_proposal(result), workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.PatchRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "patch_handler"})


def apply_check_handler(request: contracts.ApplyCheckRequest | Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        dto = _coerce_apply_check_request(request)
        result = api.apply_patch(**dto.to_api_kwargs())
        return contracts.to_response(contracts.ApplyResponse.from_result(result), workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.ApplyCheckRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "apply_check_handler"})


def apply_confirm_handler(request: contracts.ApplyConfirmRequest | Mapping[str, Any] | None = None) -> dict[str, Any]:
    try:
        dto = _coerce_apply_confirm_request(request)
        result = api.apply_patch(**dto.to_api_kwargs())
        data = contracts.ApplyResponse.from_result(result).to_dict()
        data["run_tests_requested"] = bool(dto.run_tests)
        return contracts.to_response(data, workspace=dto.workspace)
    except Exception as exc:
        workspace = request.workspace if isinstance(request, contracts.ApplyConfirmRequest) else "."
        return contracts.to_error(exc, workspace=workspace, details={"handler": "apply_confirm_handler"})
