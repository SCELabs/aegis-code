from __future__ import annotations

from pathlib import Path

import pytest

from aegis_code.api.errors import AegisPatchError
from aegis_code.api.types import ApplyResult, PatchProposal, RunReport, RunStatus, SetupStatus
from aegis_code.server.contracts import (
    API_VERSION,
    ApplyCheckRequest,
    ApplyConfirmRequest,
    ApplyResponse,
    PatchRequest,
    PatchResponse,
    ReportResponse,
    SetupCheckResponse,
    StatusResponse,
    apply_result_to_dict,
    patch_proposal_to_dict,
    run_report_to_dict,
    run_status_to_dict,
    setup_status_to_dict,
    to_error,
    to_response,
)


def test_setup_status_serialization_and_envelope() -> None:
    setup = SetupStatus.from_dict({"initialized": True, "aegis_key": True, "provider_key": False})
    data = setup_status_to_dict(setup)
    assert data["initialized"] is True
    assert data["aegis_key"] is True
    envelope = to_response(setup, workspace="repo-a")
    assert envelope["ok"] is True
    assert envelope["error"] is None
    assert envelope["data"]["initialized"] is True
    assert envelope["meta"]["api_version"] == API_VERSION
    assert envelope["meta"]["workspace"] == "repo-a"
    assert isinstance(envelope["meta"]["timestamp"], str)


def test_patch_proposal_serialization_and_response_wrapper(tmp_path: Path) -> None:
    proposal = PatchProposal(
        status="generated",
        diff_path=tmp_path / ".aegis" / "runs" / "latest.diff",
        error=None,
        operation="append",
        payload={"patch_diff": {"status": "generated"}},
        project_path=tmp_path,
    )
    data = patch_proposal_to_dict(proposal)
    assert data["status"] == "generated"
    assert isinstance(data["diff_path"], str)
    wrapped = PatchResponse.from_proposal(proposal)
    envelope = to_response(wrapped)
    assert envelope["ok"] is True
    assert "patch" in envelope["data"]


def test_apply_result_serialization_and_response_wrapper() -> None:
    apply_result = ApplyResult.from_apply_result(
        {"applied": True, "path": ".aegis/runs/latest.diff", "files_changed": [{"path": "src/app.py"}]}
    )
    data = apply_result_to_dict(apply_result)
    assert data["applied"] is True
    assert data["files_changed"] == ["src/app.py"]
    wrapped = ApplyResponse.from_result(apply_result)
    envelope = to_response(wrapped)
    assert envelope["ok"] is True
    assert envelope["data"]["apply"]["applied"] is True


def test_run_status_serialization_and_response_wrapper() -> None:
    run_status = RunStatus(
        available=True,
        task="add tests",
        run_status="completed",
        failure_count=0,
        payload={"task": "add tests", "status": "completed"},
    )
    data = run_status_to_dict(run_status)
    assert data["available"] is True
    assert data["run_status"] == "completed"
    wrapped = StatusResponse.from_status(run_status)
    envelope = to_response(wrapped)
    assert envelope["ok"] is True
    assert envelope["data"]["status"]["task"] == "add tests"


def test_run_report_serialization_and_response_wrapper(tmp_path: Path) -> None:
    report = RunReport(
        available=True,
        markdown_path=tmp_path / ".aegis" / "runs" / "latest.md",
        markdown="# Report\n",
        json_path=tmp_path / ".aegis" / "runs" / "latest.json",
        payload={"task": "x", "status": "completed", "patch_diff": {"status": "generated"}},
        project_path=tmp_path,
    )
    data = run_report_to_dict(report)
    assert data["available"] is True
    assert data["summary"]["task"] == "x"
    assert "patch" in data
    wrapped = ReportResponse.from_report(report)
    envelope = to_response(wrapped)
    assert envelope["ok"] is True
    assert envelope["data"]["report"]["summary"]["status"] == "completed"


def test_to_error_for_typed_exception_with_details() -> None:
    envelope = to_error(AegisPatchError("task is required"), workspace="repo-b", details={"request_id": "abc123"})
    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["error"]["type"] == "AegisPatchError"
    assert envelope["error"]["message"] == "task is required"
    assert envelope["error"]["details"]["code"] == "PATCH_ERROR"
    assert envelope["error"]["details"]["request_id"] == "abc123"
    assert envelope["meta"]["workspace"] == "repo-b"


def test_to_error_for_generic_exception() -> None:
    envelope = to_error(RuntimeError("boom"))
    assert envelope["ok"] is False
    assert envelope["error"]["type"] == "RuntimeError"
    assert envelope["error"]["details"]["code"] == "INTERNAL_ERROR"


def test_request_dtos_patch_apply_check_and_confirm() -> None:
    patch_request = PatchRequest(
        task="add one test",
        files=("tests/test_notes.py",),
        operation="append",
        allow_create=False,
        max_files=1,
        dry_run=False,
        mode="balanced",
        workspace="workspace-x",
    )
    patch_kwargs = patch_request.to_api_kwargs()
    assert patch_kwargs["task"] == "add one test"
    assert patch_kwargs["files"] == ["tests/test_notes.py"]
    assert patch_kwargs["operation"] == "append"
    assert patch_kwargs["project_path"] == "workspace-x"

    check_request = ApplyCheckRequest(diff_path=".aegis/runs/latest.diff", workspace="workspace-x")
    confirm_request = ApplyConfirmRequest(diff_path=".aegis/runs/latest.diff", run_tests=True, workspace="workspace-x")
    check_kwargs = check_request.to_api_kwargs()
    confirm_kwargs = confirm_request.to_api_kwargs()
    assert check_kwargs["check"] is True
    assert confirm_kwargs["check"] is False
    assert check_kwargs["path"] == ".aegis/runs/latest.diff"
    assert confirm_kwargs["path"] == ".aegis/runs/latest.diff"
    assert confirm_request.run_tests is True
    assert "run_tests" not in confirm_kwargs


def test_setup_check_response_wrapper() -> None:
    setup = SetupStatus.from_dict({"initialized": False})
    wrapped = SetupCheckResponse.from_status(setup)
    envelope = to_response(wrapped)
    assert envelope["ok"] is True
    assert "setup" in envelope["data"]


def test_to_response_rejects_unsupported_data() -> None:
    with pytest.raises(TypeError):
        to_response(123)

