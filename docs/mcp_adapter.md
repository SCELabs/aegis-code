# MCP Adapter Scaffold

## Purpose

Add a runtime-agnostic MCP adapter layer that exposes Aegis Code tools by delegating to existing server handlers.

This phase does not implement any specific MCP runtime transport.

## Module

- `aegis_code/server/mcp.py`

## Public API

- `list_tools()`
- `get_tool(name)`
- `invoke_tool(name, arguments, request_id=None)`

## Tool Categories

Read-only:

- `health`
- `setup_check`
- `status`
- `report`
- `latest_diff`

Proposal:

- `patch`

Mutation:

- `apply_check`
- `apply_confirm`

## Design Constraints

- MCP adapter calls handlers only.
- Handlers call `aegis_code.api` + contracts/guards.
- Tool output remains standardized envelope format from contracts.
- Unknown tools return standardized error envelopes.

## Validation Semantics

`invoke_tool` performs lightweight schema validation (dependency-free) against each tool's `input_schema` before dispatch:

- required field enforcement
- unknown field rejection when `additionalProperties` is false
- type validation for currently used schema types (`object`, `string`, `boolean`, `integer`, `number`, `array`)
- minimum checks for numeric fields when specified

Validation failures return a standardized error envelope with:

- `error.details.code = "INVALID_ARGUMENTS"`
- `error.details.tool`
- `error.details.validation_errors`

## Request ID Propagation

If `request_id` is provided to `invoke_tool`, it is injected into:

- `response["meta"]["request_id"]` on success
- `response["meta"]["request_id"]` on error

This allows end-to-end traceability from MCP runtime entrypoints through handler responses.

## Schema Strategy

- Lightweight manual JSON schemas are embedded in tool definitions.
- Schemas describe expected input fields, required fields, and categories.
