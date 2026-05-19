# Python API Surface (Phase 4A)

## Purpose

Define a small, stable, programmatic API for Aegis Code that mirrors the canonical CLI workflow while preserving controlled execution and safety guarantees.

## Goals

- Provide a minimal Python API for scripts, tools, agents, and integrations.
- Mirror the canonical workflow:
  1. setup/readiness
  2. patch proposal
  3. diff inspection
  4. patch application
  5. verification/check
  6. report retrieval
- Expose stable abstractions instead of internal module details.
- Preserve explicit mutation controls (`check` vs `apply`).
- Keep backward compatibility with the existing CLI/runtime behavior.

## Non-Goals

- Refactoring runtime internals in Phase 4A.
- Replacing CLI command handling.
- Exposing all internal data models as public contracts.
- Introducing broad async/event APIs yet.

## Architecture Assessment

Current stable building blocks suitable for wrapper exposure:

- setup/readiness:
  - `aegis_code.setup.check_setup`
- patch proposal core:
  - `aegis_code.runtime.run_task`
  - `aegis_code.runtime.TaskOptions`
  - `aegis_code.scope.build_scope_contract_from_cli`
- apply/check safety:
  - `aegis_code.patches.apply_check.check_patch_file`
  - `aegis_code.patches.patch_applier.apply_patch_file`
- status/report reads:
  - `aegis_code.config.project_paths`
  - `aegis_code.report.read_latest_markdown`

These are wrapped by `aegis_code.api` so consumers do not need to import internals directly.

## Public API Decision

Phase 4A provides both object-oriented and functional entry points:

- Object-oriented:
  - `AegisCode(project_path=".")`
    - `setup_check()`
    - `patch(...)`
    - `apply_patch(...)`
    - `status()`
    - `report()`
- Functional:
  - `setup_check(...)`
  - `patch(...)`
  - `apply_patch(...)`
  - `status(...)`
  - `report(...)`

Rationale:

- OO form is ergonomic for agents/integrations managing one project context.
- Functional form is lightweight for scripts and one-off automation.
- Functional helpers are thin delegations to the OO client to keep one behavior path.

## Public Return Types

`aegis_code.api.types` introduces small wrapper dataclasses:

- `SetupStatus`
- `PatchProposal`
  - includes `apply(check=True|False)` for safe check/apply flow
- `ApplyResult`
- `RunStatus`
- `RunReport`

Design notes:

- Each type includes a small normalized surface plus a `raw`/`payload` field for forward-compatible access.
- Types intentionally avoid exposing runtime-internal classes directly.

## Initial Public Surface (Phase 4A)

Module layout:

- `aegis_code/api/__init__.py`
- `aegis_code/api/client.py`
- `aegis_code/api/types.py`

Example usage:

```python
from aegis_code.api import AegisCode

client = AegisCode(project_path=".")
setup = client.setup_check()
proposal = client.patch(
    task="add tests for save_note_to_file only",
    files=["tests/test_notes.py"],
    operation="append",
)
print(proposal.status)
print(proposal.diff_path)

# Safe validation (default)
check_result = proposal.apply(check=True)

# Explicit apply
apply_result = proposal.apply(check=False)

run_status = client.status()
run_report = client.report()
```

## Stability and Compatibility Guarantees

Phase 4A guarantee:

- `aegis_code.api` module path is the public entrypoint.
- Public function/class names in `aegis_code.api.__all__` are the intended stable surface.
- Fields marked `raw`/`payload` may expand over time; existing fields are expected to remain compatible.

Internal modules that should remain private/non-contractual for now:

- `aegis_code.runtime_components.*`
- `aegis_code.providers.*`
- `aegis_code.patches.*` (except via API wrappers)
- `aegis_code.scope.*` (except wrapper usage)
- `aegis_code.cli`

## Follow-up Plan (Phase 4B+)

- Add explicit error taxonomy (`AegisApiError`, validation vs runtime vs safety errors).
- Add optional typed patch operation enums.
- Add richer diff/report helper methods (`proposal.load_diff_text()`, structured report views).
- Add async support if integration demand requires it.
