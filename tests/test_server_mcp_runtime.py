from __future__ import annotations

import aegis_code.server.mcp_runtime as runtime


def test_list_tools_passthrough(monkeypatch) -> None:
    expected = [{"name": "status", "category": "read_only", "description": "x", "input_schema": {"type": "object"}}]

    def _fake_list_tools():
        return expected

    monkeypatch.setattr("aegis_code.server.mcp_runtime.mcp_adapter.list_tools", _fake_list_tools)
    assert runtime.list_tools() == expected


def test_call_tool_passthrough(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _fake_invoke_tool(name, arguments=None, request_id=None):
        captured["name"] = name
        captured["arguments"] = arguments
        captured["request_id"] = request_id
        return {"ok": True, "data": {"status": {"available": True}}, "error": None, "meta": {"api_version": "1"}}

    monkeypatch.setattr("aegis_code.server.mcp_runtime.mcp_adapter.invoke_tool", _fake_invoke_tool)
    result = runtime.call_tool("status", {"workspace": "repo-x"}, request_id="req-77")
    assert result["ok"] is True
    assert captured["name"] == "status"
    assert captured["arguments"] == {"workspace": "repo-x"}
    assert captured["request_id"] == "req-77"


def test_call_tool_request_id_propagates_from_adapter() -> None:
    result = runtime.call_tool("status", {"workspace": "."}, request_id="req-123")
    assert result["meta"]["request_id"] == "req-123"

