# HTTP Adapter Scaffold

## Purpose

Add a framework-agnostic HTTP adapter layer that maps transport requests to `aegis_code.api` and serializes responses through `aegis_code.server.contracts`.

This phase intentionally does not introduce FastAPI, Flask, or any network serving runtime.

## Modules

- `aegis_code/server/handlers.py`
- `aegis_code/server/guards.py`

## Handler Surface

- `health_handler()`
- `setup_check_handler(...)`
- `status_handler(...)`
- `report_handler(...)`
- `latest_diff_handler(...)`
- `patch_handler(...)`
- `apply_check_handler(...)`
- `apply_confirm_handler(...)`

## Design Rules

- handlers call only:
  - `aegis_code.api`
  - `aegis_code.server.contracts`
  - `aegis_code.server.guards`
- all results return `to_response(...)` or `to_error(...)`
- `patch_handler` only proposes patches
- `apply_check_handler` and `apply_confirm_handler` are explicit and distinct

## Transport Safeguards

Implemented in `guards.py`:

- request payload size limit
- workspace string length checks
- patch task/text/file-count bounds
- diff path length checks for apply handlers

## Compatibility

- additive only
- no CLI changes
- no runtime-core refactors
- proposal-first and explicit apply-confirm semantics preserved
