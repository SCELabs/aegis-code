# Operations Architecture (Controlled Mutations)

## Purpose
Describe the current controlled mutation architecture used by scoped patch flows, including stable contracts, ownership boundaries, and extension points.

## Controlled Mutation Model
1. User or agent declares explicit mutation intent (`--operation`, scoped files, optional anchor).
2. Runtime normalizes contract and enforces scope/policy guards.
3. Operation stage builds a typed request and dependencies.
4. Operation runner dispatches to a specific operation module.
5. Operation module requests provider output, builds local diff, validates operation semantics.
6. Runtime performs broader diff validation/safety/report assembly.
7. Apply remains explicit (`apply --confirm`).

Core philosophy:
- AI proposes.
- Aegis controls.
- Developer decides.
- Tests verify.

## Current Operations
Validated:
- `append`
- `create-file`
- `insert-after`

Planned:
- `insert-before`
- `replace-block`
- `replace-symbol`
- `delete-block`
- `replace-file`

## Runtime and Operation Ownership
- `aegis_code/runtime.py`: orchestration, policy checks, verification, report payload shaping.
- `aegis_code/runtime_components/operation_stage.py`: operation-stage bridge (`run_operation_stage`), request/dependency assembly.
- `aegis_code/operations/runner.py`: typed request/result/dependencies + dispatch (`run_operation`).
- `aegis_code/operations/<operation>.py`: operation-specific execution semantics and local operation validation.
- `aegis_code/providers/prompts/`: operation prompt ownership (`append`, `create_file`, `insert_after` prompt builders).

Boundary rule:
- Runtime consumes operation results; operation modules own operation-specific provider orchestration and local mutation semantics.

## Stable Contracts

### OperationContract
Source: `aegis_code/operations/contract.py`

Primary fields:
- `operation`
- `target_file`
- `anchor`
- `symbol`
- `allow_deletions`
- `allow_new_file`
- `max_changed_lines`
- `source`

### OperationRequest
Source: `aegis_code/operations/runner.py`

Carries runtime-to-operation input:
- `contract`
- `task`
- `cwd`
- `context` (compatibility channel; still supported)
- `failures`
- `patch_plan`
- `aegis_execution`
- `model`
- `dependencies` (`OperationDependencies`, optional)
- `provider_timeout`

### OperationDependencies
Source: `aegis_code/operations/runner.py`

Typed dependency bundle for operation modules:
- provider hooks (`run_with_provider_heartbeat`, `generate_text`, `generate_structured_edits`)
- prompt builders (`build_create_file_prompt`, `build_insert_after_prompt`)
- runtime/provider metadata (`task_options`, `api_key_env`, `base_url`, `max_context_chars`)
- append validators (`append_python_sanity_error`, `validate_append_diff`)

Compatibility note:
- Operation modules prefer typed dependencies when present and fall back to `request.context` keys for backward compatibility.

### OperationResult
Source: `aegis_code/operations/runner.py`

Standard operation-stage output:
- `attempted`, `status`
- `diff_text`, `error`
- `provider`, `model`
- `validation_result`
- `operation`, `source`
- `metadata`

## Dispatch and Stage APIs

### run_operation(request)
Source: `aegis_code/operations/runner.py`

Dispatches to:
- `run_append_operation`
- `run_create_file_operation`
- `run_insert_after_operation`

Unsupported operation behavior is stable:
- `attempted=False`
- `status="blocked"`
- `error="operation_contract_invalid"`

### run_operation_stage(...)
Source: `aegis_code/runtime_components/operation_stage.py`

Bridge used by runtime operation flow:
- builds `OperationRequest`
- builds typed `OperationDependencies` from runtime values
- calls `run_operation`
- returns `OperationResult`

## Prompt Ownership
Operation prompt builders now live in:
- `aegis_code/providers/prompts/append.py`
- `aegis_code/providers/prompts/create_file.py`
- `aegis_code/providers/prompts/insert_after.py`

This keeps prompt policy modular and prevents runtime/provider base from accumulating operation-specific prompt logic.

## Error Code Model
Operation errors are explicit and stable.

Generic families:
- `operation_contract_invalid`
- `operation_target_missing`
- `operation_anchor_not_found`
- `operation_anchor_ambiguous`
- `operation_validation_failed`
- `operation_target_exists`

Current operation-specific examples:
- `append_output_invalid`
- `append_syntax_invalid`
- `append_semantic_suspicious`
- `invalid_append_operation`
- `append_source_conflict`
- `no_append_needed`
- `create_file_output_invalid`
- `insert_output_invalid`

## Reporting and Metadata
Runtime preserves operation metadata in payload/report:
- `patch_operation.operation`
- `patch_operation.source`

This metadata remains stable for diagnostics, auditing, and downstream automation.

## Compatibility Exports and Notes
- `aegis_code/operations/__init__.py` exports:
  - `OperationContract`
  - `OperationRequest`
  - `OperationDependencies`
  - `OperationResult`
  - `run_operation`
  - operation entrypoints
- Runtime compatibility wrappers are intentionally retained where tests/monkeypatching depend on runtime symbols.
- Context-based dependency lookup remains supported alongside typed dependencies.

## Adding a New Operation (Checklist)
1. Extend `OperationContract` only if new contract fields are truly required.
2. Add prompt builder(s) under `aegis_code/providers/prompts/` if operation needs custom prompting.
3. Implement `run_<operation>_operation()` in `aegis_code/operations/`.
4. Register dispatch in `run_operation()` (`aegis_code/operations/runner.py`).
5. Add/update tests:
   - operation unit tests
   - runner dispatch tests
   - runtime operation-stage flow tests
   - error-path and metadata preservation tests
6. Update docs:
   - `README.md`
   - `docs/commands.md`
   - `docs/operations.md`
