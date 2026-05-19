# Transport Contracts and DTO Layer

## Purpose

Provide a transport-neutral contract layer that:

- converts public `aegis_code.api` objects into JSON-safe DTOs
- wraps successful responses in a stable envelope
- maps typed API exceptions into a standardized error envelope

This layer is designed to be reused by:

- future HTTP endpoints
- future MCP tools
- IDE/editor integrations
- GUI frontends
- Aegis client integrations

## Module

- `aegis_code/server/contracts.py`

## Request DTOs

- `SetupCheckRequest`
- `PatchRequest`
- `ApplyCheckRequest`
- `ApplyConfirmRequest`
- `StatusRequest`
- `ReportRequest`

Each request DTO includes `to_api_kwargs()` to map transport input to `aegis_code.api` method arguments.

Design note:

- `ApplyCheckRequest` and `ApplyConfirmRequest` are explicit separate request types.
- `ApplyConfirmRequest.run_tests` is intentionally present for transport orchestration, even though it is not consumed by `aegis_code.api.apply_patch()` today.

## Response DTOs

- `SetupCheckResponse`
- `PatchResponse`
- `ApplyResponse`
- `StatusResponse`
- `ReportResponse`

Response DTOs normalize payload keys while preserving raw payload fields from the underlying API objects.

## Envelope Schema

Success envelope:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "meta": {
    "api_version": "1",
    "timestamp": "2026-01-01T00:00:00Z",
    "workspace": "."
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
    "message": "task is required",
    "details": {
      "code": "PATCH_ERROR",
      "category": "patch"
    }
  },
  "meta": {
    "api_version": "1",
    "timestamp": "2026-01-01T00:00:00Z"
  }
}
```

## Serialization Helpers

- `to_response(value, workspace=None, api_version="1", timestamp=None)`
- `to_error(exc, workspace=None, api_version="1", timestamp=None, details=None)`

Type serializers:

- `setup_status_to_dict(SetupStatus)`
- `patch_proposal_to_dict(PatchProposal)`
- `apply_result_to_dict(ApplyResult)`
- `run_status_to_dict(RunStatus)`
- `run_report_to_dict(RunReport)`

## Compatibility and Boundaries

- Additive only: no CLI behavior changes.
- Uses `aegis_code.api` as the stable integration boundary.
- Keeps proposal-first and explicit apply confirmation semantics intact.
