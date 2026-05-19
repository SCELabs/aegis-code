from __future__ import annotations

import json
from pathlib import Path

from aegis_code.api import AegisCode, apply_patch, patch, report, setup_check, status


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
