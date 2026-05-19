from __future__ import annotations

import json
from pathlib import Path

import pytest

import aegis_code.api as public_api
from aegis_code.api import (
    AegisApiError,
    AegisApplyError,
    AegisCode,
    AegisPatchError,
    AegisReportError,
    PatchOperation,
    apply_patch,
    patch,
    PatchSummary,
    ReportSummary,
    VerificationSummary,
    ModelSelectionSummary,
    RuntimeControlSummary,
    NextAction,
    report,
    setup_check,
    status,
)
from aegis_code.api.types import PatchProposal


def test_api_setup_check_returns_typed_status(tmp_path: Path) -> None:
    setup = setup_check(project_path=tmp_path)
    assert setup.initialized is False
    assert setup.aegis_key is False
    assert isinstance(setup.raw, dict)


def test_api_patch_returns_patch_proposal(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run_task(*, options, cwd=None, client=None):
        _ = client
        captured["cwd"] = cwd
        captured["task"] = options.task
        captured["patch_operation"] = options.patch_operation
        return {
            "patch_diff": {
                "status": "generated",
                "path": str((tmp_path / ".aegis" / "runs" / "latest.diff").resolve()),
                "error": None,
            },
            "patch_operation": {"operation": "append"},
        }

    monkeypatch.setattr("aegis_code.api.client.run_task", _fake_run_task)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_notes.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")

    proposal = patch(
        project_path=tmp_path,
        task="add one test",
        files=["tests/test_notes.py"],
        operation="append",
        no_report=True,
    )
    assert proposal.status == "generated"
    assert proposal.operation == "append"
    assert proposal.diff_path is not None
    assert captured["task"] == "add one test"
    assert captured["patch_operation"] == "append"
    assert Path(str(captured["cwd"])) == tmp_path


def test_api_patch_accepts_operation_enum(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_run_task(*, options, cwd=None, client=None):
        _ = cwd, client
        captured["patch_operation"] = options.patch_operation
        return {"patch_diff": {"status": "generated", "path": None, "error": None}, "patch_operation": {"operation": "append"}}

    monkeypatch.setattr("aegis_code.api.client.run_task", _fake_run_task)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_notes.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    proposal = patch(
        project_path=tmp_path,
        task="add one test",
        files=["tests/test_notes.py"],
        operation=PatchOperation.APPEND,
        no_report=True,
    )
    assert proposal.operation == "append"
    assert captured["patch_operation"] == "append"


def test_api_patch_invalid_operation_raises_typed_error(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_notes.py").write_text("def test_x():\n    assert True\n", encoding="utf-8")
    with pytest.raises(AegisPatchError):
        patch(
            project_path=tmp_path,
            task="add one test",
            files=["tests/test_notes.py"],
            operation="unsupported-op",
            no_report=True,
        )


def test_patch_proposal_apply_check_and_apply(monkeypatch, tmp_path: Path) -> None:
    diff_path = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    proposal = AegisCode(project_path=tmp_path)

    def _fake_check(path: Path, cwd: Path | None = None) -> dict[str, object]:
        _ = cwd
        return {"path": str(path), "valid": True, "apply_blocked": False, "warnings": [], "errors": []}

    def _fake_apply(path: Path, cwd: Path | None = None) -> dict[str, object]:
        _ = cwd
        return {"applied": True, "path": str(path), "warnings": [], "errors": [], "files_changed": [{"path": "x.py"}]}

    monkeypatch.setattr("aegis_code.api.types.check_patch_file", _fake_check)
    monkeypatch.setattr("aegis_code.api.types.apply_patch_file", _fake_apply)

    checked = proposal.apply_patch(path=diff_path, check=True)
    applied = proposal.apply_patch(path=diff_path, check=False)
    assert checked.valid is True
    assert checked.apply_blocked is False
    assert applied.applied is True
    assert applied.files_changed == ("x.py",)


def test_patch_proposal_diff_helpers(monkeypatch, tmp_path: Path) -> None:
    diff_path = tmp_path / ".aegis" / "runs" / "latest.diff"
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    diff_text = (
        "diff --git a/tests/test_notes.py b/tests/test_notes.py\n"
        "--- a/tests/test_notes.py\n"
        "+++ b/tests/test_notes.py\n"
        "@@ -1 +1,2 @@\n"
        " def test_x():\n"
        "+    assert True\n"
    )
    diff_path.write_text(diff_text, encoding="utf-8")

    # Build a minimal proposal via monkeypatching run_task.
    def _fake_run_task(*, options, cwd=None, client=None):
        _ = options, cwd, client
        return {
            "patch_diff": {"status": "generated", "path": str(diff_path), "error": None},
            "patch_operation": {"operation": "append"},
        }

    monkeypatch.setattr("aegis_code.api.client.run_task", _fake_run_task)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests" / "test_notes.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    built = AegisCode(project_path=tmp_path).patch(
        task="add one test",
        files=["tests/test_notes.py"],
        operation=PatchOperation.APPEND,
        no_report=True,
    )
    assert "diff --git" in built.diff_text()
    inspected = built.inspect_diff()
    assert isinstance(inspected, dict)
    assert inspected.get("summary", {}).get("file_count", 0) >= 1


def test_patch_proposal_apply_missing_diff_raises_typed_error() -> None:
    with pytest.raises(AegisApplyError):
        PatchProposal(
            status="generated",
            diff_path=None,
            error=None,
            operation="append",
            payload={},
            project_path=Path(".").resolve(),
        ).apply(check=True)


def test_api_status_and_report_read_latest_artifacts(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    payload = {"task": "x", "status": "completed", "failures": {"failure_count": 1}}
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    (runs / "latest.md").write_text("# Report\n", encoding="utf-8")

    run_status = status(project_path=tmp_path)
    run_report = report(project_path=tmp_path)
    assert run_status.available is True
    assert run_status.run_status == "completed"
    assert run_status.failure_count == 1
    assert run_report.available is True
    assert run_report.markdown is not None
    assert run_report.payload is not None
    assert run_report.raw == run_report.payload


def test_run_report_typed_views(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "x",
        "status": "completed_tests_passed",
        "mode": "balanced",
        "dry_run": False,
        "apply_safety": "HIGH",
        "failures": {"failure_count": 0},
        "patch_diff": {
            "status": "generated",
            "available": True,
            "attempted": True,
            "path": ".aegis/runs/latest.diff",
            "error": None,
            "touched_files": ["src/x.py"],
        },
        "patch_operation": {"operation": "append"},
        "verification": {
            "available": True,
            "detected_stack": "python",
            "test_command": "python -m pytest -q",
            "confidence": "high",
            "reason": "observed",
        },
        "model_selection": {
            "provider": "openai",
            "model": "gpt-4.1-mini",
            "tier": "mid",
            "mode": "balanced",
            "reason": "default",
            "provider_timeout_seconds": 60,
        },
        "runtime_policy": {"selected_mode": "balanced", "reason": "default"},
        "budget_state": {"available": True, "remaining_estimate": 0.75},
        "project_context": {"available": True},
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    (runs / "latest.md").write_text("# Report\n", encoding="utf-8")
    report_obj = report(project_path=tmp_path)

    summary = report_obj.summary
    patch_view = report_obj.patch
    verification_view = report_obj.verification
    model_view = report_obj.model_selection
    runtime_view = report_obj.runtime_control
    actions = report_obj.next_actions

    assert isinstance(summary, ReportSummary)
    assert summary.status == "completed_tests_passed"
    assert isinstance(patch_view, PatchSummary)
    assert patch_view.status == "generated"
    assert patch_view.operation == "append"
    assert patch_view.diff_path is not None
    assert patch_view.files_touched == ("src/x.py",)
    assert isinstance(verification_view, VerificationSummary)
    assert verification_view.available is True
    assert isinstance(model_view, ModelSelectionSummary)
    assert model_view.model == "gpt-4.1-mini"
    assert isinstance(runtime_view, RuntimeControlSummary)
    assert runtime_view.mode == "balanced"
    assert isinstance(actions, tuple)
    assert all(isinstance(item, NextAction) for item in actions)
    assert len(actions) > 0
    assert isinstance(actions[0].description, str)


def test_run_report_typed_views_graceful_with_missing_fields(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text(json.dumps({"task": "x"}), encoding="utf-8")
    report_obj = report(project_path=tmp_path)

    assert report_obj.summary.task == "x"
    assert report_obj.summary.failure_count == 0
    assert report_obj.patch.status == "skipped"
    assert report_obj.verification.available is False
    assert report_obj.model_selection.model is None
    assert report_obj.runtime_control.mode is None
    assert isinstance(report_obj.next_actions, tuple)
    assert len(report_obj.next_actions) >= 0


def test_run_report_next_actions_iterable_order(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "x",
        "status": "completed_tests_failed",
        "verification": {"available": True},
        "final_failures": {"failure_count": 2},
    }
    (runs / "latest.json").write_text(json.dumps(payload), encoding="utf-8")
    report_obj = report(project_path=tmp_path)
    actions = report_obj.next_actions
    assert len(actions) >= 2
    assert actions[0].index == 1
    assert actions[1].index == 2
    assert actions[0].rule == actions[1].rule


def test_latest_diff_and_report_helpers(tmp_path: Path) -> None:
    client = AegisCode(project_path=tmp_path)
    assert client.latest_diff() is None
    assert client.latest_report_json() is None
    assert client.latest_report_markdown() is None

    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    diff_path = runs / "latest.diff"
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    json_payload = {"task": "x", "status": "completed", "failures": {"failure_count": 0}}
    (runs / "latest.json").write_text(json.dumps(json_payload), encoding="utf-8")
    (runs / "latest.md").write_text("# Report\n", encoding="utf-8")

    assert client.latest_diff() == diff_path
    assert client.latest_report_json() == json_payload
    assert client.latest_report_markdown() == "# Report\n"


def test_latest_report_json_invalid_raises_typed_error(tmp_path: Path) -> None:
    runs = tmp_path / ".aegis" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "latest.json").write_text("{invalid-json", encoding="utf-8")
    with pytest.raises(AegisReportError):
        AegisCode(project_path=tmp_path).latest_report_json()


def test_apply_patch_missing_latest_diff_raises_typed_error(tmp_path: Path) -> None:
    with pytest.raises(AegisApplyError):
        apply_patch(project_path=tmp_path, check=True)


def test_patch_wrapper_invalid_inputs_raise_typed_error(tmp_path: Path) -> None:
    with pytest.raises(AegisPatchError):
        patch(project_path=tmp_path, task="", files=["x.py"])
    with pytest.raises(AegisPatchError):
        patch(project_path=tmp_path, task="x", files=[])


def test_base_api_error_is_public() -> None:
    with pytest.raises(AegisApiError):
        raise AegisPatchError("boom")


def test_api_apply_patch_uses_latest_diff_by_default(monkeypatch, tmp_path: Path) -> None:
    latest_diff = tmp_path / ".aegis" / "runs" / "latest.diff"
    latest_diff.parent.mkdir(parents=True, exist_ok=True)
    latest_diff.write_text("diff --git a/x b/x\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_check(path: Path, cwd: Path | None = None) -> dict[str, object]:
        captured["path"] = str(path)
        captured["cwd"] = str(cwd) if cwd is not None else None
        return {"path": str(path), "valid": True, "apply_blocked": False, "warnings": [], "errors": []}

    monkeypatch.setattr("aegis_code.api.types.check_patch_file", _fake_check)
    result = apply_patch(project_path=tmp_path, check=True)
    assert result.valid is True
    assert Path(str(captured["path"])) == latest_diff
    assert Path(str(captured["cwd"])) == tmp_path


def test_public_api_exports_match_documented_surface() -> None:
    expected_exports = {
        "AegisCode",
        "AegisApiError",
        "AegisSetupError",
        "AegisPatchError",
        "AegisApplyError",
        "AegisReportError",
        "PatchOperation",
        "PatchOperationValue",
        "SetupStatus",
        "PatchProposal",
        "ApplyResult",
        "ReportSummary",
        "PatchSummary",
        "VerificationSummary",
        "ModelSelectionSummary",
        "RuntimeControlSummary",
        "NextAction",
        "RunStatus",
        "RunReport",
        "setup_check",
        "patch",
        "apply_patch",
        "status",
        "report",
    }
    assert set(public_api.__all__) == expected_exports


def test_python_api_docs_cover_phase4d_reference_sections() -> None:
    root = Path(__file__).resolve().parents[1]
    api_doc = (root / "docs" / "python_api_surface_phase4a.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "# Python API Reference (Phase 4D)" in api_doc
    assert "## Quickstart" in api_doc
    assert "## End-to-End Example" in api_doc
    assert "## Public API Reference" in api_doc
    assert "## Exceptions Reference" in api_doc
    assert "## Operations Reference" in api_doc
    assert "## Typed Report Views" in api_doc
    assert "## Public vs Private Modules" in api_doc
    assert "## Stability Guarantees" in api_doc
    assert "docs/python_api_surface_phase4a.md" in readme
