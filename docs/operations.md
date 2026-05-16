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
- `insert-before`
- `replace-block`
- `delete-block`
- `replace-file`
- `delete-file`
- `replace-symbol`
- `delete-symbol`
- `rename-file`
- `move-file`
- `batch` (Phase 1 schema validation only; execution not implemented)

Source of truth:
- `aegis_code/operations/registry.py` defines operation names and metadata (requirements, provider-required/provider-free, deletion/new-file capabilities).

`replace-block` notes:
- anchor semantics are exact block text matching (line-ending normalized, no fuzzy/symbol-aware matching yet)
- deletions are allowed only inside the uniquely matched block span being replaced

`delete-block` notes:
- anchor semantics are exact block text matching (line-ending normalized, no fuzzy/symbol-aware matching yet)
- the uniquely matched block span is removed from a single target file

`replace-file` notes:
- rewrites full contents of an explicit existing target file
- still proposal-first, locally diff-validated, and safety-gated before apply

`delete-file` notes:
- removes an explicit existing target file
- provider-free operation with local deletion diff generation and validation

`replace-symbol` notes:
- replaces one uniquely resolved symbol in an explicit existing target file
- initial resolution support is conservative:
  - Python: `def`, `async def`, and `class` definitions
  - JS/TS: function declarations and `const` arrow functions (with or without `export`)

`delete-symbol` notes:
- provider-free operation that removes one uniquely resolved symbol in an explicit existing target file
- uses the same conservative symbol resolution rules as `replace-symbol`
- when symbol resolution is unsupported for a file pattern, use `replace-block` as a fallback operation mode

`rename-file` notes:
- provider-free operation that renames one explicit existing source path to one explicit destination path
- source and destination must be different
- destination must not already exist
- generated diff is deterministic and validated as a one-file rename with unchanged contents

`move-file` notes:
- provider-free operation that moves one explicit existing source path to one explicit destination path
- uses the same deterministic one-file relocation model as `rename-file`
- source and destination must be different
- destination must not already exist

`batch` notes (Phase 1):
- composite operation definition is validated from JSON (`version`, `operations`, step requirements)
- nested `batch` steps are rejected
- execution is intentionally not implemented in Phase 1

## Runtime and Operation Ownership
- `aegis_code/runtime.py`: orchestration, policy checks, verification, report payload shaping.
- `aegis_code/runtime_components/operation_stage.py`: operation-stage bridge (`run_operation_stage`), request/dependency assembly.
- `aegis_code/operations/runner.py`: typed request/result/dependencies + dispatch (`run_operation`).
- `aegis_code/operations/<operation>.py`: operation-specific execution semantics and local operation validation.
- `aegis_code/providers/prompts/`: operation prompt ownership (`append`, `create_file`, `insert_after`, `insert_before`, `replace_block`, `replace_file`, `replace_symbol` prompt builders).

Boundary rule:
- Runtime consumes operation results; operation modules own operation-specific provider orchestration and local mutation semantics.

## Stable Contracts

### OperationContract
Source: `aegis_code/operations/contract.py`

Primary fields:
- `operation`
- `target_file`
- `destination_path`
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
- `destination_path` (optional; used by destination-style operations such as `rename-file` and `move-file`)
- `dependencies` (`OperationDependencies`, optional)
- `provider_timeout`

### OperationDependencies
Source: `aegis_code/operations/runner.py`

Typed dependency bundle for operation modules:
- provider hooks (`run_with_provider_heartbeat`, `generate_text`, `generate_structured_edits`)
- prompt builders (`build_create_file_prompt`, `build_insert_after_prompt`, `build_insert_before_prompt`, `build_replace_block_prompt`, `build_replace_file_prompt`, `build_replace_symbol_prompt`)
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
- `run_insert_before_operation`
- `run_replace_block_operation`
- `run_delete_block_operation`
- `run_replace_file_operation`
- `run_delete_file_operation`
- `run_replace_symbol_operation`
- `run_delete_symbol_operation`
- `run_rename_file_operation`
- `run_move_file_operation`

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
- `aegis_code/providers/prompts/insert_before.py`
- `aegis_code/providers/prompts/replace_block.py`

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
- `operation_symbol_not_found`
- `operation_symbol_ambiguous`

Current operation-specific examples:
- `append_output_invalid`
- `append_syntax_invalid`
- `append_semantic_suspicious`
- `invalid_append_operation`
- `append_source_conflict`
- `no_append_needed`
- `create_file_output_invalid`
- `insert_output_invalid`
- `replace_block_output_invalid`
- `replace_file_output_invalid`
- `replace_symbol_output_invalid`

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
1. Register operation metadata in `aegis_code/operations/registry.py`.
2. Extend `OperationContract` only if new contract fields are truly required.
3. Add prompt builder(s) under `aegis_code/providers/prompts/` if operation needs custom prompting.
4. Implement `run_<operation>_operation()` in `aegis_code/operations/`.
5. Register dispatch in `run_operation()` (`aegis_code/operations/runner.py`).
6. Add/update tests:
   - operation unit tests
   - runner dispatch tests
   - runtime operation-stage flow tests
   - error-path and metadata preservation tests
7. Update docs:
   - `README.md`
   - `docs/commands.md`
   - `docs/operations.md`
