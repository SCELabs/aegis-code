# Batch Operation RFC (Design Only)

Status: Draft RFC for design only. No production behavior change is introduced by this document.

## 1. Goals

- Add a new composite controlled mutation operation: `batch`.
- Allow multiple existing controlled operations to be proposed as one atomic proposal artifact.
- Preserve Aegis principles:
  - AI proposes.
  - Aegis controls.
  - Developer decides.
  - Tests verify.
- Reuse current architecture:
  - operation registry as source of truth
  - operation contracts
  - operation-stage execution
  - deterministic local diff validation
  - existing safety/apply gates

## 2. Non-Goals

- No autonomous planning loops.
- No nested/composite recursion (`batch` inside `batch`) in v1.
- No parallel execution in v1.
- No apply-time transactional filesystem rollback in v1 (batch remains proposal-first).
- No broad refactor of operation runner dispatch in v1.

## 3. Proposed Batch JSON Schema

```json
{
  "version": 1,
  "operations": [
    {
      "operation": "create-file",
      "target_file": "src/utils.js",
      "task": "Create utility helpers."
    },
    {
      "operation": "replace-symbol",
      "target_file": "src/main.js",
      "symbol": "run",
      "task": "Use the new utility helpers."
    }
  ],
  "options": {
    "stop_on_first_failure": true
  }
}
```

### Schema notes (v1)

- Required root fields:
  - `version` (must be `1`)
  - `operations` (non-empty array)
- Operation item fields:
  - required: `operation`, `target_file`, `task`
  - optional: `anchor`, `symbol`, `destination_path`
- Disallowed in v1:
  - `operation: batch`
  - unknown operation names
  - empty task text

## 4. Runtime Execution Flow

1. CLI command:
   - `aegis-code patch --operation batch --batch-file <path>`
2. Load and parse batch JSON.
3. Validate each step against operation registry metadata:
   - supported operation
   - required fields present (`anchor`, `symbol`, `destination_path` as applicable)
4. Create isolated temporary workspace copy from project root.
5. Execute step operations sequentially in temp workspace using existing operation-stage path:
   - construct per-step `OperationContract`
   - call operation stage/runner
   - apply generated step diff to temp workspace only (never real workspace)
6. Abort immediately on first failed/blocked/invalid step.
7. If all steps succeed:
   - compute one combined diff between original workspace and temp workspace
   - run existing diff validation + safety on combined diff
8. Emit one proposal payload and diff artifact for normal `apply` flow.

## 5. Validation Flow

Both step-level and combined validation are required.

- Step-level validation:
  - each step must pass its existing operation validation semantics
  - ensures local correctness and contract compliance
- Combined validation:
  - inspect final combined diff with existing diff inspector/check pipeline
  - enforce allowed-target and plan consistency on union of batch targets

Rationale: step-only misses aggregate safety regressions; combined-only hides which step caused failure.

## 6. Safety Model

Use dual safety evaluation.

- Per-step safety:
  - run existing operation-level and patch-policy checks during step execution in temp workspace
- Combined safety:
  - run standard patch safety review on final combined diff (authoritative gate for apply)

Apply gating remains unchanged:
- `LOW` / `BLOCKED` safety can still block apply unless existing bounded exceptions apply.

## 7. Rollback Strategy

v1 rollback strategy is workspace-isolation, not in-place revert.

- Because all step execution happens in temp workspace:
  - failure rollback = discard temp workspace
  - no mutation in real workspace has occurred
- Apply-time rollback is unchanged from existing apply/backup flow.

This provides strong atomic proposal semantics with minimal new risk.

## 8. Reporting Model

Add batch-aware reporting while preserving existing payload conventions.

- Top-level `patch_operation`:
  - `operation: "batch"`
  - `source: "cli"`
- Add `batch_report` section:
  - `total_steps`
  - `completed_steps`
  - `failed_step_index` (if any)
  - `steps`: array with per-step status and diagnostics
- Combined summary:
  - final `patch_diff.status`
  - combined validation + safety
  - touched files union

Example step status values:
- `generated`
- `blocked`
- `invalid`
- `unavailable`
- `skipped_due_to_prior_failure`

## 9. Conflict Detection

v1 conflict detection rules:

- Allowed:
  - multiple steps touching same file sequentially
- Blocked:
  - same-step malformed overlap signals (existing operation validation failure)
  - destination/source path collisions (for rename/move/create/delete)
  - operations whose required preconditions are invalid at step execution time

Deterministic conflict handling:
- execute in listed order
- later steps see the file state produced by earlier accepted steps in temp workspace
- first failing step aborts batch

## 10. Failure Modes

Representative failure reasons:

- `batch_file_invalid_json`
- `batch_schema_invalid`
- `batch_operation_unsupported`
- `batch_nested_operation_not_allowed`
- `batch_step_contract_invalid`
- `batch_step_failed` (with step-level underlying operation error)
- `batch_combined_validation_failed`
- `batch_combined_safety_blocked`

Failure output should include:
- failing step index
- failing step operation/target
- mapped underlying operation error code when available

## 11. Minimal v1 Constraints

- Sequential execution only.
- No nested batches.
- No parallel step execution.
- Abort on first failure.
- Execute in temporary workspace copy only.
- Produce a single combined diff only if all steps succeed.
- Run safety on combined diff before proposal acceptance.
- Run tests once after apply (existing apply flow), not per step.

## 12. Future Extensions

- Optional preflight planning pass:
  - provider proposes step ordering/shape under explicit constraints
- Optional per-step verification modes:
  - selective lint/test checkpoints for long batches
- Step grouping / micro-transactions:
  - commit checkpoints in temp workspace for richer diagnostics
- Partial-success modes (opt-in, non-default):
  - produce best-effort subset diff with explicit degraded status
- Agent/API batch endpoint:
  - typed batch request payload with registry-backed validation helpers

## Key Design Decisions

1. Atomicity model: proposal-atomic, all-or-nothing at proposal generation.
2. Rollback model: discard temp workspace on failure.
3. Validation model: step-level plus combined.
4. Safety model: step-level plus combined; combined is apply-authoritative.
5. Execution model: strict sequential, deterministic, fail-closed.

## Suggested Implementation Phases

### Phase 1: Schema + CLI Surface
- Add `batch` operation metadata to operation registry.
- Add `--batch-file` CLI flag and parser validation.
- Parse and normalize batch file into internal batch-step list.

### Phase 2: Batch Executor in Temp Workspace
- Build temp workspace orchestration.
- Run existing operation stage per step with current contracts.
- Apply accepted step diff to temp workspace state only.

### Phase 3: Combined Diff + Safety + Reporting
- Compute final combined diff.
- Run existing validation/safety pipeline on combined diff.
- Emit batch-aware reporting payload with per-step diagnostics.

### Phase 4: Hardening + Guardrails
- Expand conflict checks and path-collision diagnostics.
- Add focused regression tests for failure mapping and deterministic ordering.
- Document agent/API submission guidance.
