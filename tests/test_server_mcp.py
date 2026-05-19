from __future__ import annotations

import aegis_code.server.mcp as mcp


def test_list_tools_includes_expected_names_and_schema() -> None:
    tools = mcp.list_tools()
    names = {item["name"] for item in tools}
    assert "health" in names
    assert "setup_check" in names
    assert "status" in names
    assert "report" in names
    assert "latest_diff" in names
    assert "patch" in names
    assert "apply_check" in names
    assert "apply_confirm" in names

    patch_tool = next(item for item in tools if item["name"] == "patch")
    assert patch_tool["category"] == "proposal"
    assert patch_tool["input_schema"]["type"] == "object"
    assert "properties" in patch_tool["input_schema"]
    assert "task" in patch_tool["input_schema"]["properties"]
    assert "files" in patch_tool["input_schema"]["properties"]


def test_patch_invoke_delegates_to_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_patch_handler(arguments):
        captured["arguments"] = dict(arguments)
        return {"ok": True, "data": {"patch": {"status": "generated"}}, "error": None, "meta": {"api_version": "1"}}

    monkeypatch.setattr("aegis_code.server.mcp.handlers.patch_handler", _fake_patch_handler)
    result = mcp.invoke_tool("patch", {"workspace": "repo", "task": "x", "files": ["a.py"]})
    assert result["ok"] is True
    assert captured["arguments"]["task"] == "x"
    assert captured["arguments"]["files"] == ["a.py"]


def test_patch_invoke_missing_required_field_returns_validation_error() -> None:
    result = mcp.invoke_tool("patch", {"workspace": "repo", "files": ["a.py"]})
    assert result["ok"] is False
    assert result["error"]["details"]["code"] == "INVALID_ARGUMENTS"
    assert result["error"]["details"]["tool"] == "patch"
    assert any("task" in item and "required" in item for item in result["error"]["details"]["validation_errors"])


def test_unknown_field_returns_validation_error() -> None:
    result = mcp.invoke_tool("status", {"workspace": "repo", "unexpected": True})
    assert result["ok"] is False
    assert result["error"]["details"]["code"] == "INVALID_ARGUMENTS"
    assert any("unexpected" in item and "not allowed" in item for item in result["error"]["details"]["validation_errors"])


def test_apply_check_invoke_delegates_to_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_apply_check_handler(arguments):
        captured["arguments"] = dict(arguments)
        return {"ok": True, "data": {"apply": {"valid": True}}, "error": None, "meta": {"api_version": "1"}}

    monkeypatch.setattr("aegis_code.server.mcp.handlers.apply_check_handler", _fake_apply_check_handler)
    result = mcp.invoke_tool("apply_check", {"workspace": "repo", "diff_path": ".aegis/runs/latest.diff"})
    assert result["ok"] is True
    assert captured["arguments"]["diff_path"] == ".aegis/runs/latest.diff"


def test_apply_confirm_invoke_delegates_to_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_apply_confirm_handler(arguments):
        captured["arguments"] = dict(arguments)
        return {"ok": True, "data": {"apply": {"applied": True}}, "error": None, "meta": {"api_version": "1"}}

    monkeypatch.setattr("aegis_code.server.mcp.handlers.apply_confirm_handler", _fake_apply_confirm_handler)
    result = mcp.invoke_tool("apply_confirm", {"workspace": "repo", "run_tests": True})
    assert result["ok"] is True
    assert captured["arguments"]["run_tests"] is True


def test_unknown_tool_returns_standard_error_envelope() -> None:
    result = mcp.invoke_tool("does_not_exist", {"workspace": "repo"})
    assert result["ok"] is False
    assert result["error"]["details"]["code"] == "UNKNOWN_TOOL"
    assert result["error"]["details"]["tool"] == "does_not_exist"
    assert "patch" in result["error"]["details"]["available_tools"]
    assert "status" in result["error"]["details"]["valid_tool_names"]


def test_request_id_propagates_on_success(monkeypatch) -> None:
    def _fake_status_handler(arguments):
        _ = arguments
        return {"ok": True, "data": {"status": {"available": True}}, "error": None, "meta": {"api_version": "1"}}

    monkeypatch.setattr("aegis_code.server.mcp.handlers.status_handler", _fake_status_handler)
    result = mcp.invoke_tool("status", {"workspace": "repo"}, request_id="req-123")
    assert result["ok"] is True
    assert result["meta"]["request_id"] == "req-123"


def test_request_id_propagates_on_error() -> None:
    result = mcp.invoke_tool("patch", {"workspace": "repo", "files": ["a.py"]}, request_id="req-err")
    assert result["ok"] is False
    assert result["meta"]["request_id"] == "req-err"
