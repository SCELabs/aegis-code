# HTTP/MCP Server Design Audit (Phase 5A)

## Purpose

Define a design-first blueprint for exposing Aegis Code as:

1. an HTTP service
2. an MCP server
3. a foundation for IDE/editor integrations and autonomous agents

This design must preserve the core product model:

- AI proposes.
- Aegis controls.
- Developer decides.
- Tests verify.

## Scope

Phase 5A is design-only:

- no broad server implementation
- no CLI behavior changes
- no core runtime refactors

Minimal scaffolding may be added in a later phase when design decisions are accepted.

## Goals

- Map the existing public Python API to server-safe interfaces.
- Keep proposal-first semantics explicit across transports.
- Separate read-only, proposal, and mutation operations.
- Preserve safety checks, apply gating, and verification workflows.
- Define stable request/response conventions for typed API objects.

## Non-Goals

- Implementing a production HTTP framework in Phase 5A.
- Implementing a full MCP runtime in Phase 5A.
- Replacing the CLI as the canonical local interface.
- Relaxing mutation controls or introducing auto-apply behavior.

## Architecture Assessment

Current stable programmatic surface is `aegis_code.api`:

- `AegisCode.setup_check()`
- `AegisCode.patch(...)`
- `AegisCode.apply_patch(path=None, check=True)`
- `AegisCode.status()`
- `AegisCode.report()`
- `AegisCode.latest_diff()`
- `AegisCode.latest_report_json()`
- `AegisCode.latest_report_markdown()`

Typed API return objects:

- `SetupStatus`
- `PatchProposal`
- `ApplyResult`
- `RunStatus`
- `RunReport` with typed views (`summary`, `patch`, `verification`, `model_selection`, `runtime_control`, `next_actions`)

Typed API errors:

- `AegisApiError` (base)
- `AegisSetupError`
- `AegisPatchError`
- `AegisApplyError`
- `AegisReportError`

Conclusion:

- The existing public API is suitable as the server integration boundary.
- Server layers should call `aegis_code.api` wrappers rather than runtime internals.

## Server Suitability Classification

### Read-only operations

- `setup_check`
- `status`
- `report`
- `latest_diff` (read artifact text/path only)
- `latest_report_json`
- `latest_report_markdown`

Notes:

- These operations may read `.aegis` artifacts and configuration.
- They should never mutate source files.

### Proposal operations

- `patch`

Notes:

- `patch` is non-mutating for source files.
- It can create/update run artifacts (for example diff/report files under `.aegis/runs`).
- Treat as controlled proposal generation, not pure read-only.

### Mutation operations

- `apply_patch(check=True)` -> validation/check mode (non-mutating source files)
- `apply_patch(check=False)` -> confirm/apply mode (mutates source files)

Recommendation:

- Do not expose a single ambiguous "apply" action remotely.
- Split transport surface into explicit check and confirm endpoints/tools.

## Trust Boundaries

### Boundary A: Client -> Server transport

Risk:

- malformed inputs
- oversized payloads
- unauthorized mutation attempts

Controls:

- explicit schemas and validation
- authentication and authorization
- rate limiting and request size limits

### Boundary B: Server adapter -> Public API (`aegis_code.api`)

Risk:

- bypassing public contracts
- leaking unstable internals

Controls:

- call public API methods only
- map typed exceptions to stable transport error codes
- keep internal exceptions private

### Boundary C: API -> Local workspace filesystem

Risk:

- cross-project access
- unintended path traversal
- concurrent mutation races

Controls:

- explicit workspace root per request/session
- normalize/resolve paths under approved root
- per-workspace operation lock for proposal/apply flows

### Boundary D: API -> Provider/network

Risk:

- unbounded provider requests
- cost/latency variability

Controls:

- preserve budget/runtime policy controls
- preserve provider timeout controls
- expose runtime-control metadata in responses

## Request/Response Model

## Common request fields

- `project_path` (required or derived from authenticated session/workspace)
- operation-specific fields (for example `task`, `files`, `operation`)
- optional controls:
  - `mode`
  - `budget`
  - `provider_timeout_seconds`
  - `session`

## Common response envelope

Recommended transport envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "request_id": "uuid",
    "project_path": ".",
    "api_version": "v1"
  }
}
```

Error envelope:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "type": "AegisPatchError",
    "code": "PATCH_INVALID_INPUT",
    "message": "task is required"
  },
  "meta": {
    "request_id": "uuid",
    "api_version": "v1"
  }
}
```

## HTTP Endpoint Mapping (Proposed)

### Health and readiness

- `GET /health`
  - purpose: process-level liveness
  - response: service version, uptime, optional dependency health summary

- `GET /setup/check`
  - maps to: `setup_check`
  - class: read-only

### Inspection and diagnostics

- `GET /status`
  - maps to: `status`
  - class: read-only

- `GET /report`
  - maps to: `report`
  - class: read-only

- `GET /report/latest.json`
  - maps to: `latest_report_json`
  - class: read-only

- `GET /report/latest.md`
  - maps to: `latest_report_markdown`
  - class: read-only

- `GET /diff/latest`
  - maps to: `latest_diff` (+ file read)
  - class: read-only

### Proposal generation

- `POST /patch`
  - maps to: `patch`
  - class: proposal
  - behavior: proposal-first only; no source-file mutation

### Apply flow

- `POST /apply/check`
  - maps to: `apply_patch(check=true)` or `PatchProposal.apply(check=true)`
  - class: mutation-gate check (non-mutating source files)
  - behavior: validate apply safety and block state

- `POST /apply/confirm`
  - maps to: `apply_patch(check=false)` or `PatchProposal.apply(check=false)`
  - class: mutation
  - behavior: explicit mutation action; never implied by `/patch`

## MCP Tool Mapping (Proposed)

Recommended initial MCP tools:

- `setup_check`
- `status`
- `report`
- `latest_diff`
- `patch`
- `apply_check`
- `apply_confirm`

Compatibility alias option:

- `apply_patch` can be retained as a compatibility tool that requires explicit `check` boolean.
- Prefer `apply_check` and `apply_confirm` as canonical MCP tools to avoid accidental mutation ambiguity.

## Proposal and Confirmation Semantics

Required invariants across HTTP and MCP:

1. `patch` must never mutate source files.
2. apply confirmation must be explicit transport action.
3. "check" and "confirm" must not share a default that can silently apply.
4. mutation endpoints/tools should return safety/result metadata and changed files.

Recommended flow for clients:

1. `setup_check`
2. `patch`
3. `latest_diff` or diff preview from patch response
4. `apply_check`
5. human/user confirmation step in client UI/agent policy
6. `apply_confirm`
7. `report` and `status`

## Safety Model Preservation

Server adapters must preserve current control behavior:

- proposal-first generation
- deterministic local diff inspection and apply checks
- explicit confirmation required for mutation
- existing patch safety controls and block semantics
- runtime policy and budget controls
- verification access through existing report/status outputs

No server transport should bypass:

- scope contract constraints
- patch operation validation
- apply safety gating

## Authentication and Authorization Considerations

Phase 5A recommendation:

- HTTP: bearer token or mTLS for service access
- MCP: host-provided trust plus optional per-tool authorization policy

Authorization should support at least:

- read-only role (`setup_check`, `status`, `report`, `latest_*`)
- proposal role (read-only + `patch`)
- mutation role (proposal + `apply_confirm`)

For local single-user mode, auth may be optional but should be explicit in configuration.

## Session and Workspace Considerations

- Every request/tool call should resolve to one explicit `project_path` workspace root.
- Multi-workspace support should be session-scoped, not global mutable process state.
- Use per-workspace locks for proposal/apply operations to prevent race conditions.
- Return relative artifact paths where possible; avoid leaking absolute host paths by default.

## Serialization Strategy for Public API Types

Use JSON-serializable DTOs built from public API objects.

Recommended rules:

- dataclass-like objects -> plain dictionaries
- `Path` -> string
- tuples -> arrays
- preserve booleans/numbers/strings/null as native JSON types
- include `raw`/`payload` fields for forward compatibility

Example DTO conventions:

- `setup_check` -> `SetupStatus` fields + `raw`
- `patch` -> `status`, `diff_path`, `error`, `operation`, `payload`
- `apply_check` and `apply_confirm` -> `ApplyResult` fields + `raw`
- `status` -> `RunStatus` fields + `raw`
- `report` -> normalized top-level fields + typed views + `raw`

Versioning recommendation:

- transport schema version in response meta (for example `api_version: v1`)
- additive fields allowed
- breaking schema changes require version bump

## Error Mapping Recommendation

Map public exceptions to transport errors:

- `AegisSetupError` -> setup/readiness error class
- `AegisPatchError` -> validation/proposal error class
- `AegisApplyError` -> apply validation/mutation error class
- `AegisReportError` -> artifact/report retrieval error class

Fallback unknown exceptions:

- internal error code with sanitized message
- include request id for traceability

## Minimal Scaffold Recommendation (Deferred)

No implementation is required in Phase 5A.

If a minimal scaffold is introduced in a follow-up phase, keep it thin:

- `aegis_code/server/http_contract.py` (schemas, DTO serialization helpers)
- `aegis_code/server/mcp_contract.py` (tool definitions and argument mapping)
- `aegis_code/server/service.py` (public API orchestration only)

No runtime-core refactors should be required.

## Phase 5A Summary

The current `aegis_code.api` surface is suitable for HTTP and MCP exposure with a thin adapter layer.

Key design decisions:

- Use public API as the only server integration boundary.
- Keep mutation explicit with split check vs confirm operations.
- Preserve proposal-first semantics and safety controls end-to-end.
- Adopt stable, versioned JSON serialization with forward-compatible `raw` payload access.
