from __future__ import annotations

from pathlib import Path

from aegis_code.api.errors import AegisPatchError
from aegis_code.api.types import ApplyResult, PatchProposal
from aegis_code.server.contracts import ApplyCheckRequest, ApplyConfirmRequest, PatchRequest
from aegis_code.server.handlers import (
    apply_check_handler,
    apply_confirm_handler,
    health_handler,
    patch_handler,
)


def test_health_handler_returns_envelope() -> None:
    result = health_handler(workspace="repo-x")
    assert result["ok"] is True
    assert result["error"] is None
    assert result["data"]["health"]["status"] == "ok"
    assert result["meta"]["workspace"] == "repo-x"


def test_patch_handler_routes_to_api_patch_only(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {"patched": False, "applied": False}

    def _fake_patch(**kwargs):
        captured["patched"] = True
        captured["kwargs"] = kwargs
        return PatchProposal(
            status="generated",
            diff_path=tmp_path / ".aegis" / "runs" / "latest.diff",
            error=None,
            operation="append",
            payload={"patch_diff": {"status": "generated"}, "patch_operation": {"operation": "append"}},
            project_path=tmp_path,
        )

    def _fake_apply_patch(**kwargs):
        _ = kwargs
        captured["applied"] = True
        return ApplyResult.from_check_result({"valid": True, "apply_blocked": False, "path": None, "warnings": [], "errors": []})

    monkeypatch.setattr("aegis_code.server.handlers.api.patch", _fake_patch)
    monkeypatch.setattr("aegis_code.server.handlers.api.apply_patch", _fake_apply_patch)

    response = patch_handler(
        PatchRequest(
            task="add one test",
            files=("tests/test_notes.py",),
            operation="append",
            workspace=str(tmp_path),
        )
    )
    assert response["ok"] is True
    assert captured["patched"] is True
    assert captured["applied"] is False
    assert response["data"]["patch"]["status"] == "generated"


def test_apply_check_handler_uses_check_true(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_apply_patch(**kwargs):
        captured["kwargs"] = kwargs
        return ApplyResult.from_check_result(
            {"valid": True, "apply_blocked": False, "path": ".aegis/runs/latest.diff", "warnings": [], "errors": []}
        )

    monkeypatch.setattr("aegis_code.server.handlers.api.apply_patch", _fake_apply_patch)
    response = apply_check_handler(ApplyCheckRequest(diff_path=".aegis/runs/latest.diff", workspace=str(tmp_path)))
    assert response["ok"] is True
    assert captured["kwargs"]["check"] is True
    assert response["data"]["apply"]["valid"] is True


def test_apply_confirm_handler_uses_check_false_and_keeps_run_tests_flag(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def _fake_apply_patch(**kwargs):
        captured["kwargs"] = kwargs
        return ApplyResult.from_apply_result(
            {"applied": True, "path": ".aegis/runs/latest.diff", "warnings": [], "errors": [], "files_changed": [{"path": "x.py"}]}
        )

    monkeypatch.setattr("aegis_code.server.handlers.api.apply_patch", _fake_apply_patch)
    response = apply_confirm_handler(
        ApplyConfirmRequest(diff_path=".aegis/runs/latest.diff", run_tests=True, workspace=str(tmp_path))
    )
    assert response["ok"] is True
    assert captured["kwargs"]["check"] is False
    assert response["data"]["apply"]["applied"] is True
    assert response["data"]["run_tests_requested"] is True


def test_patch_handler_returns_error_envelope(monkeypatch, tmp_path: Path) -> None:
    def _fake_patch(**kwargs):
        _ = kwargs
        raise AegisPatchError("task is required")

    monkeypatch.setattr("aegis_code.server.handlers.api.patch", _fake_patch)
    response = patch_handler(
        PatchRequest(
            task="",
            files=("tests/test_notes.py",),
            operation="append",
            workspace=str(tmp_path),
        )
    )
    assert response["ok"] is False
    assert response["error"]["type"] == "AegisPatchError"
    assert response["error"]["details"]["code"] == "PATCH_ERROR"
    assert response["error"]["details"]["handler"] == "patch_handler"
