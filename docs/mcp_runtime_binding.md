# MCP Runtime Binding

## Purpose

Provide a tiny runtime-facing binding that any MCP host can wrap immediately without introducing framework dependencies.

## Module

- `aegis_code/server/mcp_runtime.py`

## Public API

- `list_tools()`
- `call_tool(name, arguments=None, request_id=None)`

## Design

- `list_tools()` delegates directly to `aegis_code.server.mcp.list_tools()`.
- `call_tool(...)` delegates directly to `aegis_code.server.mcp.invoke_tool(...)`.
- No business logic is duplicated in the runtime binding.
- Responses remain the standardized envelopes produced by the contracts layer.

## Notes

- No stdio/network server is started in this layer.
- Runtime hosts are expected to handle transport wiring and lifecycle management.
