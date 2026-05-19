from __future__ import annotations

from typing import Any, Mapping

import aegis_code.server.mcp as mcp_adapter


def list_tools() -> list[dict[str, Any]]:
    """Runtime-facing passthrough for MCP tool discovery."""
    return mcp_adapter.list_tools()


def call_tool(
    name: str,
    arguments: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Runtime-facing passthrough for MCP tool invocation."""
    return mcp_adapter.invoke_tool(name=name, arguments=arguments, request_id=request_id)

